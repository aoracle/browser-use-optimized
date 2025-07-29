"""Browser pool for efficient browser instance management."""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.browser.types import Browser, BrowserContext

logger = logging.getLogger(__name__)


class BrowserPool:
	"""Pool of browser instances for improved performance and resource management."""
	
	def __init__(
		self,
		max_browsers: int = 5,
		max_contexts_per_browser: int = 10,
		browser_profile: Optional[BrowserProfile] = None,
	):
		"""Initialize browser pool.
		
		Args:
			max_browsers: Maximum number of browser instances to maintain
			max_contexts_per_browser: Maximum contexts per browser instance
			browser_profile: Default browser profile for new instances
		"""
		self.max_browsers = max_browsers
		self.max_contexts_per_browser = max_contexts_per_browser
		self.browser_profile = browser_profile or BrowserProfile()
		
		self._browsers: list[BrowserSession] = []
		self._available_browsers: asyncio.Queue[BrowserSession] = asyncio.Queue()
		self._context_counts: dict[BrowserSession, int] = {}
		self._lock = asyncio.Lock()
		self._initialized = False
		self._shutdown = False
		
	async def initialize(self) -> None:
		"""Initialize the browser pool with minimum browsers."""
		if self._initialized:
			return
			
		async with self._lock:
			if self._initialized:
				return
				
			logger.info(f"Initializing browser pool with max {self.max_browsers} browsers")
			
			# Start with one browser
			browser = await self._create_browser()
			self._browsers.append(browser)
			self._context_counts[browser] = 0
			await self._available_browsers.put(browser)
			
			self._initialized = True
			logger.info("Browser pool initialized")
	
	async def _create_browser(self) -> BrowserSession:
		"""Create a new browser instance."""
		browser = BrowserSession(browser_profile=self.browser_profile)
		await browser.start()
		logger.debug(f"Created new browser instance (total: {len(self._browsers) + 1})")
		return browser
	
	@asynccontextmanager
	async def acquire_context(self) -> AsyncIterator[tuple[BrowserSession, BrowserContext]]:
		"""Acquire a browser context from the pool."""
		if not self._initialized:
			await self.initialize()
		
		browser = None
		context = None
		
		try:
			# Try to get an available browser
			browser = await self._get_available_browser()
			
			# Create a new context
			context = await browser.browser_context.new_context()
			
			async with self._lock:
				self._context_counts[browser] += 1
				logger.debug(f"Acquired context (browser contexts: {self._context_counts[browser]})")
			
			yield browser, context
			
		finally:
			# Clean up context
			if context:
				try:
					await context.close()
				except Exception as e:
					logger.warning(f"Error closing context: {e}")
			
			# Return browser to pool
			if browser:
				async with self._lock:
					if browser in self._context_counts:
						self._context_counts[browser] -= 1
						
						# Check if browser should be returned to available pool
						if self._context_counts[browser] < self.max_contexts_per_browser:
							await self._available_browsers.put(browser)
						else:
							logger.debug(f"Browser at capacity ({self._context_counts[browser]} contexts)")
	
	async def _get_available_browser(self) -> BrowserSession:
		"""Get an available browser from the pool."""
		while not self._shutdown:
			try:
				# Try to get a browser with timeout
				browser = await asyncio.wait_for(
					self._available_browsers.get(),
					timeout=0.1
				)
				
				# Verify browser is still healthy
				if browser.browser and not browser.browser.is_connected():
					logger.warning("Got disconnected browser from pool, creating new one")
					async with self._lock:
						if browser in self._browsers:
							self._browsers.remove(browser)
						if browser in self._context_counts:
							del self._context_counts[browser]
					continue
				
				# Check if browser has capacity
				async with self._lock:
					if self._context_counts.get(browser, 0) < self.max_contexts_per_browser:
						return browser
					else:
						# Put it back and try again
						await self._available_browsers.put(browser)
						
			except asyncio.TimeoutError:
				# No available browsers, try to create a new one
				async with self._lock:
					if len(self._browsers) < self.max_browsers:
						browser = await self._create_browser()
						self._browsers.append(browser)
						self._context_counts[browser] = 0
						return browser
				
				# At capacity, wait a bit and retry
				await asyncio.sleep(0.1)
		
		raise RuntimeError("Browser pool is shutting down")
	
	async def shutdown(self) -> None:
		"""Shutdown the browser pool and close all browsers."""
		logger.info("Shutting down browser pool")
		self._shutdown = True
		
		async with self._lock:
			# Close all browsers
			close_tasks = []
			for browser in self._browsers:
				close_tasks.append(browser.close())
			
			if close_tasks:
				await asyncio.gather(*close_tasks, return_exceptions=True)
			
			self._browsers.clear()
			self._context_counts.clear()
			self._initialized = False
			
		logger.info("Browser pool shutdown complete")
	
	def get_stats(self) -> dict:
		"""Get pool statistics."""
		return {
			'total_browsers': len(self._browsers),
			'available_browsers': self._available_browsers.qsize(),
			'context_counts': dict(self._context_counts),
			'max_browsers': self.max_browsers,
			'max_contexts_per_browser': self.max_contexts_per_browser,
		}


# Global browser pool instance
_global_browser_pool: Optional[BrowserPool] = None


def get_browser_pool() -> BrowserPool:
	"""Get the global browser pool instance."""
	global _global_browser_pool
	if _global_browser_pool is None:
		_global_browser_pool = BrowserPool()
	return _global_browser_pool


async def shutdown_browser_pool() -> None:
	"""Shutdown the global browser pool."""
	global _global_browser_pool
	if _global_browser_pool:
		await _global_browser_pool.shutdown()
		_global_browser_pool = None