"""Retry utilities with exponential backoff and jitter."""
import asyncio
import logging
import random
from functools import wraps
from typing import Any, Callable, Optional, Type, Union

logger = logging.getLogger(__name__)


class RetryConfig:
	"""Configuration for retry behavior."""
	
	def __init__(
		self,
		max_retries: int = 3,
		initial_delay: float = 1.0,
		max_delay: float = 60.0,
		exponential_base: float = 2.0,
		jitter: bool = True,
		exceptions: tuple[Type[Exception], ...] = (Exception,),
	):
		"""Initialize retry configuration.
		
		Args:
			max_retries: Maximum number of retry attempts
			initial_delay: Initial delay in seconds
			max_delay: Maximum delay in seconds
			exponential_base: Base for exponential backoff
			jitter: Whether to add random jitter to delays
			exceptions: Tuple of exceptions to retry on
		"""
		self.max_retries = max_retries
		self.initial_delay = initial_delay
		self.max_delay = max_delay
		self.exponential_base = exponential_base
		self.jitter = jitter
		self.exceptions = exceptions
		
	def calculate_delay(self, attempt: int) -> float:
		"""Calculate delay for a given attempt number."""
		delay = min(
			self.initial_delay * (self.exponential_base ** (attempt - 1)),
			self.max_delay
		)
		
		if self.jitter:
			# Add random jitter between 0 and 25% of the delay
			jitter_amount = delay * 0.25 * random.random()
			delay += jitter_amount
			
		return delay


def retry_async(
	config: Optional[RetryConfig] = None,
	*,
	max_retries: Optional[int] = None,
	initial_delay: Optional[float] = None,
	exceptions: Optional[tuple[Type[Exception], ...]] = None,
):
	"""Decorator for async functions with exponential backoff retry.
	
	Args:
		config: RetryConfig instance or None to use defaults
		max_retries: Override max retries from config
		initial_delay: Override initial delay from config
		exceptions: Override exceptions from config
	"""
	if config is None:
		config = RetryConfig()
		
	# Override config values if provided
	if max_retries is not None:
		config.max_retries = max_retries
	if initial_delay is not None:
		config.initial_delay = initial_delay
	if exceptions is not None:
		config.exceptions = exceptions
		
	def decorator(func: Callable) -> Callable:
		@wraps(func)
		async def wrapper(*args, **kwargs) -> Any:
			last_exception = None
			
			for attempt in range(1, config.max_retries + 2):
				try:
					return await func(*args, **kwargs)
				except config.exceptions as e:
					last_exception = e
					
					if attempt > config.max_retries:
						logger.error(
							f"Failed {func.__name__} after {config.max_retries} retries: {type(e).__name__}: {str(e)}"
						)
						raise
						
					delay = config.calculate_delay(attempt)
					logger.warning(
						f"Retry {attempt}/{config.max_retries} for {func.__name__} "
						f"after {type(e).__name__}: {str(e)} "
						f"(waiting {delay:.1f}s)"
					)
					
					await asyncio.sleep(delay)
					
			# Should never reach here, but just in case
			if last_exception:
				raise last_exception
				
		return wrapper
	return decorator


def retry_sync(
	config: Optional[RetryConfig] = None,
	*,
	max_retries: Optional[int] = None,
	initial_delay: Optional[float] = None,
	exceptions: Optional[tuple[Type[Exception], ...]] = None,
):
	"""Decorator for sync functions with exponential backoff retry.
	
	Args:
		config: RetryConfig instance or None to use defaults
		max_retries: Override max retries from config
		initial_delay: Override initial delay from config
		exceptions: Override exceptions from config
	"""
	if config is None:
		config = RetryConfig()
		
	# Override config values if provided
	if max_retries is not None:
		config.max_retries = max_retries
	if initial_delay is not None:
		config.initial_delay = initial_delay
	if exceptions is not None:
		config.exceptions = exceptions
		
	def decorator(func: Callable) -> Callable:
		@wraps(func)
		def wrapper(*args, **kwargs) -> Any:
			last_exception = None
			
			for attempt in range(1, config.max_retries + 2):
				try:
					return func(*args, **kwargs)
				except config.exceptions as e:
					last_exception = e
					
					if attempt > config.max_retries:
						logger.error(
							f"Failed {func.__name__} after {config.max_retries} retries: {type(e).__name__}: {str(e)}"
						)
						raise
						
					delay = config.calculate_delay(attempt)
					logger.warning(
						f"Retry {attempt}/{config.max_retries} for {func.__name__} "
						f"after {type(e).__name__}: {str(e)} "
						f"(waiting {delay:.1f}s)"
					)
					
					import time
					time.sleep(delay)
					
			# Should never reach here, but just in case
			if last_exception:
				raise last_exception
				
		return wrapper
	return decorator


# Convenience decorators with common configurations
retry_browser_operation = retry_async(
	RetryConfig(
		max_retries=3,
		initial_delay=0.5,
		max_delay=10.0,
		exceptions=(
			RuntimeError,
			ConnectionError,
			TimeoutError,
		)
	)
)

retry_network_operation = retry_async(
	RetryConfig(
		max_retries=5,
		initial_delay=1.0,
		max_delay=30.0,
		exceptions=(
			ConnectionError,
			TimeoutError,
			OSError,
		)
	)
)


class CircuitBreaker:
	"""Circuit breaker pattern for preventing cascading failures."""
	
	def __init__(
		self,
		failure_threshold: int = 5,
		recovery_timeout: float = 60.0,
		expected_exception: Type[Exception] = Exception,
	):
		"""Initialize circuit breaker.
		
		Args:
			failure_threshold: Number of failures before opening circuit
			recovery_timeout: Time in seconds before attempting recovery
			expected_exception: Exception type to track
		"""
		self.failure_threshold = failure_threshold
		self.recovery_timeout = recovery_timeout
		self.expected_exception = expected_exception
		
		self._failure_count = 0
		self._last_failure_time: Optional[float] = None
		self._state: str = 'closed'  # closed, open, half-open
		
	@property
	def state(self) -> str:
		"""Get current circuit breaker state."""
		if self._state == 'open':
			# Check if we should transition to half-open
			if self._last_failure_time:
				import time
				if time.time() - self._last_failure_time > self.recovery_timeout:
					self._state = 'half-open'
					logger.info(f"Circuit breaker transitioning to half-open")
					
		return self._state
		
	def call(self, func: Callable, *args, **kwargs) -> Any:
		"""Call function with circuit breaker protection."""
		if self.state == 'open':
			raise RuntimeError("Circuit breaker is open")
			
		try:
			result = func(*args, **kwargs)
			self._on_success()
			return result
		except self.expected_exception as e:
			self._on_failure()
			raise
			
	async def async_call(self, func: Callable, *args, **kwargs) -> Any:
		"""Call async function with circuit breaker protection."""
		if self.state == 'open':
			raise RuntimeError("Circuit breaker is open")
			
		try:
			result = await func(*args, **kwargs)
			self._on_success()
			return result
		except self.expected_exception as e:
			self._on_failure()
			raise
			
	def _on_success(self) -> None:
		"""Handle successful call."""
		if self._state == 'half-open':
			logger.info("Circuit breaker closing after successful call")
			self._state = 'closed'
			
		self._failure_count = 0
		self._last_failure_time = None
		
	def _on_failure(self) -> None:
		"""Handle failed call."""
		import time
		self._failure_count += 1
		self._last_failure_time = time.time()
		
		if self._failure_count >= self.failure_threshold:
			logger.error(f"Circuit breaker opening after {self._failure_count} failures")
			self._state = 'open'
		elif self._state == 'half-open':
			logger.warning("Circuit breaker reopening after failure in half-open state")
			self._state = 'open'