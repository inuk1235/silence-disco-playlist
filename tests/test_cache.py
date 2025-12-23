import unittest
import asyncio
from unittest.mock import MagicMock
from api.app.cache import AsyncTTLCache
import time

class TestAsyncTTLCache(unittest.TestCase):
    def test_cache_logic(self):
        async def run_test():
            mock_func = MagicMock()

            @AsyncTTLCache(ttl=1)
            async def test_func():
                mock_func()
                return "result"

            # First call
            res1 = await test_func()
            self.assertEqual(res1, "result")
            self.assertEqual(mock_func.call_count, 1)

            # Second call (immediate) - should be cached
            res2 = await test_func()
            self.assertEqual(res2, "result")
            self.assertEqual(mock_func.call_count, 1)

            # Wait for TTL to expire
            await asyncio.sleep(1.1)

            # Third call - should run again
            res3 = await test_func()
            self.assertEqual(res3, "result")
            self.assertEqual(mock_func.call_count, 2)

        asyncio.run(run_test())

    def test_cache_args(self):
        async def run_test():
            mock_func = MagicMock()

            @AsyncTTLCache(ttl=10)
            async def test_func(arg):
                mock_func(arg)
                return f"result-{arg}"

            await test_func("A")
            await test_func("A") # Cached
            await test_func("B") # New arg

            self.assertEqual(mock_func.call_count, 2)
            mock_func.assert_any_call("A")
            mock_func.assert_any_call("B")

        asyncio.run(run_test())

if __name__ == '__main__':
    unittest.main()
