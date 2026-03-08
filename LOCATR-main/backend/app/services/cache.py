import time
from typing import Any, Optional, Dict

class SimpleTTLCache:
    """
    A lightweight in-memory cache with Time-To-Live (TTL).
    Useful for hackathon/demo apps to avoid redundant slow API calls.
    """
    def __init__(self, default_ttl: int = 300): # 5 minutes default
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        if key not in self._cache:
            return None
        
        entry = self._cache[key]
        if time.time() > entry["expires"]:
            del self._cache[key]
            return None
            
        return entry["value"]

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        ttl = ttl if ttl is not None else self.default_ttl
        self._cache[key] = {
            "value": value,
            "expires": time.time() + ttl
        }

# Global cache instance
search_cache = SimpleTTLCache()
