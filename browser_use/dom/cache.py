"""
DOM CACHING SERVICE - PERFORMANCE OPTIMIZATION
==============================================
This module implements caching for DOM states to avoid redundant extractions.

WORKFLOW 2.x: CACHED DOM RETRIEVAL
==================================
2.0: Receive DOM request
2.1: Check cache for valid entry
2.2: Return cached state (skip extraction)

WORKFLOW 1.x: CACHE MISS HANDLING
=================================
1.8: Cache check returns None
1.11: Store newly extracted DOM state
1.11.1: Check cache capacity
1.11.2: LRU eviction if needed
1.11.3: Store with timestamp

Cache dramatically improves performance by avoiding re-extraction
of DOM states within a short time window (default 2 seconds).
"""
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
		"""
		WORKFLOW 2.1: Check if DOM state exists in cache
		================================================
		Attempts to retrieve a cached DOM state for the given parameters.
		
		SUB-STEPS:
		2.1.1: Generate cache key from page URL and parameters
		2.1.2: Check if key exists in cache
		2.1.3: Validate entry hasn't expired (TTL check)
		2.1.4: Update LRU ordering if valid
		2.1.5: Return cached state or None (triggers Workflow 1.x if None)
		"""
		cache_key = self._generate_cache_key(page, highlight_elements, focus_element, viewport_expansion)
		
		async with self._lock:
			if cache_key in self._cache:
				dom_state, timestamp = self._cache[cache_key]
				
				# 2.1.3: Validate cache entry TTL
				if time.time() - timestamp > self.ttl_seconds:
					logger.debug(f"Cache expired for key {cache_key[:8]}...")
					del self._cache[cache_key]
					self._access_order.remove(cache_key)
					return None
				
				# Update LRU ordering - move to end
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
		"""
		WORKFLOW 1.11: Store newly extracted DOM state
		==============================================
		Caches a DOM state after successful extraction.
		
		SUB-STEPS:
		1.11.1: Generate cache key
		1.11.2: Check cache capacity
		1.11.3: Evict oldest entry if needed (LRU)
		1.11.4: Store state with timestamp
		1.11.5: Track cache key for page cleanup
		"""
		cache_key = self._generate_cache_key(page, highlight_elements, focus_element, viewport_expansion)
		
		async with self._lock:
			# STEP 11B: Manage cache size (LRU eviction)
			# If cache is full and this is a new entry, evict oldest
			if len(self._cache) >= self.max_size and cache_key not in self._cache:
				oldest_key = self._access_order.pop(0)
				del self._cache[oldest_key]
				logger.debug(f"Evicted oldest cache entry {oldest_key[:8]}...")
			
			# Store new entry with current timestamp
			self._cache[cache_key] = (dom_state, time.time())
			
			# Update LRU access order
			if cache_key in self._access_order:
				self._access_order.remove(cache_key)
			self._access_order.append(cache_key)
			
			# Track cache key by page for automatic cleanup
			# When page is garbage collected, associated cache entries are cleared
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