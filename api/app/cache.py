import time
from functools import wraps
import asyncio

class AsyncTTLCache:
    """
    A simple TTL (Time-To-Live) cache for async functions.
    Stores results in memory for a specified duration.
    """
    def __init__(self, ttl: int = 60):
        self.ttl = ttl
        self._cache = {}

    def __call__(self, func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Create a cache key based on function name, args, and kwargs
            # We sort kwargs to ensure consistency
            key = (
                func.__name__,
                args,
                frozenset(sorted(kwargs.items()))
            )

            now = time.time()
            if key in self._cache:
                result, timestamp = self._cache[key]
                if now - timestamp < self.ttl:
                    return result

            # Call the actual function
            result = await func(*args, **kwargs)

            # Store result with timestamp
            self._cache[key] = (result, now)

            return result
        return wrapper
