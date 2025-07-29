"""DOM caching service for performance optimization."""
import asyncio
import hashlib
import logging
import time
from typing import Any, Optional
from weakref import WeakKeyDictionary

from browser_use.browser.types import Page
from browser_use.dom.views import DOMState
from browser_use.utils import time_execution_async

logger = logging.getLogger(__name__)


class DOMCache:
	"""Cache for DOM states to avoid redundant DOM tree construction."""
	
	def __init__(self, ttl_seconds: float = 2.0, max_size: int = 100):
		"""Initialize DOM cache.
		
		Args:
			ttl_seconds: Time to live for cache entries in seconds
			max_size: Maximum number of entries in cache
		"""
		self.ttl_seconds = ttl_seconds
		self.max_size = max_size
		self._cache: dict[str, tuple[DOMState, float]] = {}
		self._access_order: list[str] = []
		self._lock = asyncio.Lock()
		# Track cache per page to auto-cleanup when page is garbage collected
		self._page_caches: WeakKeyDictionary[Page, set[str]] = WeakKeyDictionary()
		
	def _generate_cache_key(
		self,
		page: Page,
		highlight_elements: bool,
		focus_element: int,
		viewport_expansion: int,
	) -> str:
		"""Generate cache key based on page state and parameters."""
		# Include page URL and timestamp to invalidate on navigation
		key_parts = [
			page.url,
			str(highlight_elements),
			str(focus_element),
			str(viewport_expansion),
		]
		key_str = '|'.join(key_parts)
		return hashlib.md5(key_str.encode()).hexdigest()
	
	async def get(
		self,
		page: Page,
		highlight_elements: bool,
		focus_element: int,
		viewport_expansion: int,
	) -> Optional[DOMState]:
		"""Get cached DOM state if available and not expired."""
		cache_key = self._generate_cache_key(page, highlight_elements, focus_element, viewport_expansion)
		
		async with self._lock:
			if cache_key in self._cache:
				dom_state, timestamp = self._cache[cache_key]
				
				# Check if cache entry is expired
				if time.time() - timestamp > self.ttl_seconds:
					logger.debug(f"Cache expired for key {cache_key[:8]}...")
					del self._cache[cache_key]
					self._access_order.remove(cache_key)
					return None
				
				# Move to end for LRU
				self._access_order.remove(cache_key)
				self._access_order.append(cache_key)
				
				logger.debug(f"Cache hit for key {cache_key[:8]}...")
				return dom_state
		
		return None
	
	async def set(
		self,
		page: Page,
		highlight_elements: bool,
		focus_element: int,
		viewport_expansion: int,
		dom_state: DOMState,
	) -> None:
		"""Store DOM state in cache."""
		cache_key = self._generate_cache_key(page, highlight_elements, focus_element, viewport_expansion)
		
		async with self._lock:
			# Evict oldest entry if cache is full
			if len(self._cache) >= self.max_size and cache_key not in self._cache:
				oldest_key = self._access_order.pop(0)
				del self._cache[oldest_key]
				logger.debug(f"Evicted oldest cache entry {oldest_key[:8]}...")
			
			# Store new entry
			self._cache[cache_key] = (dom_state, time.time())
			if cache_key in self._access_order:
				self._access_order.remove(cache_key)
			self._access_order.append(cache_key)
			
			# Track cache key for this page
			if page not in self._page_caches:
				self._page_caches[page] = set()
			self._page_caches[page].add(cache_key)
			
			logger.debug(f"Cached DOM state for key {cache_key[:8]}... (cache size: {len(self._cache)})")
	
	async def invalidate_page(self, page: Page) -> None:
		"""Invalidate all cache entries for a specific page."""
		async with self._lock:
			if page in self._page_caches:
				for cache_key in self._page_caches[page]:
					if cache_key in self._cache:
						del self._cache[cache_key]
						self._access_order.remove(cache_key)
				del self._page_caches[page]
				logger.debug(f"Invalidated cache for page {page.url[:50]}...")
	
	async def clear(self) -> None:
		"""Clear all cache entries."""
		async with self._lock:
			self._cache.clear()
			self._access_order.clear()
			self._page_caches.clear()
			logger.debug("Cleared all DOM cache entries")
	
	def get_stats(self) -> dict[str, Any]:
		"""Get cache statistics."""
		return {
			'size': len(self._cache),
			'max_size': self.max_size,
			'ttl_seconds': self.ttl_seconds,
			'pages_tracked': len(self._page_caches),
		}


# Global cache instance
_global_dom_cache = DOMCache()


def get_dom_cache() -> DOMCache:
	"""Get the global DOM cache instance."""
	return _global_dom_cache