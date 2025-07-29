"""Memory management utilities for browser-use."""
import asyncio
import gc
import logging
import os
import sys
import psutil
import weakref
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MemoryManager:
	"""Manages memory usage and prevents memory leaks."""
	
	def __init__(
		self,
		max_memory_mb: int = 2048,
		gc_threshold_mb: int = 1024,
		check_interval: float = 30.0,
	):
		"""Initialize memory manager.
		
		Args:
			max_memory_mb: Maximum memory usage in MB before forcing cleanup
			gc_threshold_mb: Memory threshold in MB to trigger garbage collection
			check_interval: Interval in seconds between memory checks
		"""
		self.max_memory_mb = max_memory_mb
		self.gc_threshold_mb = gc_threshold_mb
		self.check_interval = check_interval
		
		self._process = psutil.Process(os.getpid())
		self._monitor_task: Optional[asyncio.Task] = None
		self._tracked_objects: weakref.WeakSet = weakref.WeakSet()
		self._memory_callbacks: list[callable] = []
		
	def track_object(self, obj: Any) -> None:
		"""Track an object for memory management."""
		self._tracked_objects.add(obj)
		
	def add_memory_callback(self, callback: callable) -> None:
		"""Add a callback to be called when memory cleanup is needed."""
		self._memory_callbacks.append(callback)
		
	async def start_monitoring(self) -> None:
		"""Start the memory monitoring task."""
		if self._monitor_task:
			return
			
		self._monitor_task = asyncio.create_task(self._monitor_memory())
		logger.info(f"Started memory monitoring (max: {self.max_memory_mb}MB, gc threshold: {self.gc_threshold_mb}MB)")
		
	async def stop_monitoring(self) -> None:
		"""Stop the memory monitoring task."""
		if self._monitor_task:
			self._monitor_task.cancel()
			try:
				await self._monitor_task
			except asyncio.CancelledError:
				pass
			self._monitor_task = None
			logger.info("Stopped memory monitoring")
			
	async def _monitor_memory(self) -> None:
		"""Monitor memory usage and trigger cleanup when needed."""
		while True:
			try:
				memory_mb = self.get_memory_usage_mb()
				
				# Log memory usage periodically
				logger.debug(f"Memory usage: {memory_mb:.1f}MB / {self.max_memory_mb}MB")
				
				# Check if we need to trigger garbage collection
				if memory_mb > self.gc_threshold_mb:
					logger.warning(f"Memory usage high ({memory_mb:.1f}MB), triggering garbage collection")
					await self.cleanup_memory()
					
				# Check if we're approaching max memory
				if memory_mb > self.max_memory_mb * 0.9:
					logger.error(f"Memory usage critical ({memory_mb:.1f}MB), forcing aggressive cleanup")
					await self.force_cleanup()
					
				await asyncio.sleep(self.check_interval)
				
			except Exception as e:
				logger.error(f"Error in memory monitor: {e}")
				await asyncio.sleep(self.check_interval)
				
	def get_memory_usage_mb(self) -> float:
		"""Get current memory usage in MB."""
		return self._process.memory_info().rss / (1024 * 1024)
		
	def get_memory_stats(self) -> dict:
		"""Get detailed memory statistics."""
		memory_info = self._process.memory_info()
		return {
			'rss_mb': memory_info.rss / (1024 * 1024),
			'vms_mb': memory_info.vms / (1024 * 1024),
			'percent': self._process.memory_percent(),
			'tracked_objects': len(self._tracked_objects),
			'gc_stats': gc.get_stats(),
		}
		
	async def cleanup_memory(self) -> None:
		"""Perform memory cleanup."""
		logger.info("Performing memory cleanup...")
		
		# Clear tracked objects that are no longer referenced
		tracked_before = len(self._tracked_objects)
		self._tracked_objects = weakref.WeakSet(obj for obj in self._tracked_objects)
		tracked_after = len(self._tracked_objects)
		
		if tracked_before > tracked_after:
			logger.debug(f"Cleared {tracked_before - tracked_after} dead tracked objects")
		
		# Call registered cleanup callbacks
		for callback in self._memory_callbacks:
			try:
				if asyncio.iscoroutinefunction(callback):
					await callback()
				else:
					callback()
			except Exception as e:
				logger.error(f"Error in memory cleanup callback: {e}")
		
		# Run garbage collection
		gc.collect()
		
		# Log memory usage after cleanup
		memory_after = self.get_memory_usage_mb()
		logger.info(f"Memory cleanup complete (usage: {memory_after:.1f}MB)")
		
	async def force_cleanup(self) -> None:
		"""Force aggressive memory cleanup."""
		logger.warning("Forcing aggressive memory cleanup...")
		
		# Clear all caches
		gc.collect(2)  # Full collection
		
		# Clear tracked objects
		self._tracked_objects.clear()
		
		# Call all cleanup callbacks
		await self.cleanup_memory()
		
		# Additional aggressive cleanup
		# Clear module-level caches if any
		for module in list(sys.modules.values()):
			if hasattr(module, '_cache'):
				try:
					module._cache.clear()
				except:
					pass
					
		logger.warning(f"Aggressive cleanup complete (usage: {self.get_memory_usage_mb():.1f}MB)")


# Global memory manager instance
_global_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
	"""Get the global memory manager instance."""
	global _global_memory_manager
	if _global_memory_manager is None:
		_global_memory_manager = MemoryManager()
	return _global_memory_manager


# Decorator to track memory usage of functions
def track_memory(func):
	"""Decorator to track memory usage of a function."""
	async def async_wrapper(*args, **kwargs):
		manager = get_memory_manager()
		before = manager.get_memory_usage_mb()
		
		try:
			result = await func(*args, **kwargs)
			return result
		finally:
			after = manager.get_memory_usage_mb()
			delta = after - before
			if delta > 10:  # Log if memory increased by more than 10MB
				logger.warning(f"{func.__name__} increased memory by {delta:.1f}MB")
				
	def sync_wrapper(*args, **kwargs):
		manager = get_memory_manager()
		before = manager.get_memory_usage_mb()
		
		try:
			result = func(*args, **kwargs)
			return result
		finally:
			after = manager.get_memory_usage_mb()
			delta = after - before
			if delta > 10:  # Log if memory increased by more than 10MB
				logger.warning(f"{func.__name__} increased memory by {delta:.1f}MB")
				
	if asyncio.iscoroutinefunction(func):
		return async_wrapper
	else:
		return sync_wrapper