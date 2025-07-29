"""Simplified browser health checking utilities."""
import asyncio
import logging
from functools import wraps
from typing import Optional

from browser_use.browser.types import Page
from browser_use.retry_utils import retry_async, RetryConfig

logger = logging.getLogger(__name__)


class BrowserHealthChecker:
	"""Efficient browser health checking."""
	
	def __init__(self, timeout: float = 5.0):
		"""Initialize health checker.
		
		Args:
			timeout: Timeout for health check operations
		"""
		self.timeout = timeout
		self._health_cache: dict[Page, tuple[bool, float]] = {}
		self._cache_ttl = 2.0  # Cache health status for 2 seconds
		
	async def is_page_healthy(self, page: Optional[Page]) -> bool:
		"""Check if a page is healthy and responsive.
		
		Args:
			page: Page to check
			
		Returns:
			True if page is healthy, False otherwise
		"""
		if not page:
			return False
			
		try:
			# Check cache first
			import time
			if page in self._health_cache:
				is_healthy, timestamp = self._health_cache[page]
				if time.time() - timestamp < self._cache_ttl:
					return is_healthy
					
			# Basic checks
			if page.is_closed():
				self._health_cache[page] = (False, time.time())
				return False
				
			# Quick JavaScript evaluation to test responsiveness
			try:
				result = await asyncio.wait_for(
					page.evaluate('1 + 1'),
					timeout=self.timeout
				)
				is_healthy = result == 2
			except (asyncio.TimeoutError, Exception):
				is_healthy = False
				
			# Cache result
			self._health_cache[page] = (is_healthy, time.time())
			return is_healthy
			
		except Exception as e:
			logger.debug(f"Health check failed: {e}")
			return False
			
	async def ensure_page_ready(self, page: Page) -> None:
		"""Ensure page is ready for interaction.
		
		Args:
			page: Page to prepare
		"""
		try:
			# Wait for page to be in a stable state
			await asyncio.wait_for(
				page.wait_for_load_state('domcontentloaded'),
				timeout=self.timeout
			)
		except asyncio.TimeoutError:
			logger.warning("Page load timeout, continuing anyway")
		except Exception as e:
			logger.debug(f"Page readiness check failed: {e}")
			
	def clear_cache(self, page: Optional[Page] = None) -> None:
		"""Clear health check cache.
		
		Args:
			page: Specific page to clear, or None to clear all
		"""
		if page:
			self._health_cache.pop(page, None)
		else:
			self._health_cache.clear()


# Global health checker instance
_global_health_checker = BrowserHealthChecker()


def healthy_browser_required(func):
	"""Simplified decorator to ensure browser health before operation."""
	@wraps(func)
	async def wrapper(self, *args, **kwargs):
		# Quick health check
		if hasattr(self, 'agent_current_page') and self.agent_current_page:
			if not await _global_health_checker.is_page_healthy(self.agent_current_page):
				logger.warning(f"Page unhealthy before {func.__name__}, attempting recovery")
				
				# Simple recovery: try to create a new page
				if hasattr(self, 'browser_context') and self.browser_context:
					try:
						self.agent_current_page = await self.browser_context.new_page()
						logger.info("Created new page for recovery")
					except Exception as e:
						logger.error(f"Failed to create new page: {e}")
						# Continue anyway, let the operation fail if needed
						
		return await func(self, *args, **kwargs)
		
	return wrapper


# Retry configuration for browser operations
browser_retry_config = RetryConfig(
	max_retries=3,
	initial_delay=0.5,
	max_delay=5.0,
	exceptions=(RuntimeError, ConnectionError, TimeoutError),
)


def with_browser_retry(func):
	"""Decorator that combines health check and retry logic."""
	@wraps(func)
	@retry_async(browser_retry_config)
	@healthy_browser_required
	async def wrapper(*args, **kwargs):
		return await func(*args, **kwargs)
	return wrapper