"""
Shared cache utility for routines to store and retrieve data.

Supports multiple backends with automatic fallback:
1. Redis (fast, shared across all containers) - tries first if REDIS_URL set
2. JSON file cache (fallback, works without Redis)

Usage:
    from utils.shared_cache import get_cached, set_cached
    
    # Get cached data
    data = get_cached("my_key", max_age_minutes=60)
    
    # Set cached data
    set_cached("my_key", {"my": "data"})
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Cache directory (fallback)
CACHE_DIR = Path("/root/.condor/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Redis connection (lazy init)
_redis_client = None
_redis_available = None


def _get_redis():
    """Get Redis client with lazy initialization and connection pooling."""
    global _redis_client, _redis_available
    
    # Return cached result if already checked
    if _redis_available is False:
        return None
    
    if _redis_client is not None:
        return _redis_client
    
    # Try to connect to Redis
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379")
    
    try:
        import redis
        _redis_client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=False
        )
        # Test connection
        _redis_client.ping()
        _redis_available = True
        logger.debug(f"Redis connected at {redis_url}")
        return _redis_client
    except Exception as exc:
        logger.debug(f"Redis not available ({exc}), using file cache fallback")
        _redis_available = False
        return None


class SharedCache:
    """
    Shared cache that persists data across routine runs.
    Automatically uses Redis if available, falls back to JSON files.
    """
    
    @staticmethod
    def get(key: str, max_age_minutes: int = 60) -> dict[str, Any] | None:
        """
        Get cached data if it exists and isn't expired.
        
        Args:
            key: Cache key (alphanumeric, underscores, hyphens)
            max_age_minutes: Maximum age in minutes before considering stale
            
        Returns:
            Cached data dict or None if not found/expired
        """
        # Try Redis first
        redis_client = _get_redis()
        if redis_client:
            try:
                cached_str = redis_client.get(f"cache:{key}")
                if cached_str:
                    cache_data = json.loads(cached_str)
                    cached_at = datetime.fromisoformat(cache_data.get("cached_at", "2000-01-01"))
                    
                    if datetime.now() - cached_at <= timedelta(minutes=max_age_minutes):
                        logger.debug(f"Redis cache hit for key: {key}")
                        return cache_data.get("data")
                    else:
                        # Expired, delete it
                        redis_client.delete(f"cache:{key}")
                        logger.debug(f"Redis cache expired for key: {key}")
                return None
            except Exception as exc:
                logger.warning(f"Redis get failed for {key}: {exc}, falling back to file cache")
        
        # Fallback to file cache
        cache_file = CACHE_DIR / f"{key}.json"
        
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)
            
            # Check expiry
            cached_at = datetime.fromisoformat(cache_data.get("cached_at", "2000-01-01"))
            if datetime.now() - cached_at > timedelta(minutes=max_age_minutes):
                logger.debug(f"Cache expired for key: {key}")
                return None
            
            logger.debug(f"Cache hit for key: {key}")
            return cache_data.get("data")
            
        except Exception as exc:
            logger.warning(f"Failed to read cache for {key}: {exc}")
            return None
    
    @staticmethod
    def set(key: str, data: dict[str, Any], ttl_seconds: int | None = None) -> bool:
        """
        Store data in cache with current timestamp.
        
        Args:
            key: Cache key (alphanumeric, underscores, hyphens)
            data: Data to cache (must be JSON-serializable)
            ttl_seconds: Optional TTL in seconds (Redis only, for automatic expiration)
            
        Returns:
            True if successful, False otherwise
        """
        cache_data = {
            "cached_at": datetime.now().isoformat(),
            "data": data
        }
        
        # Try Redis first
        redis_client = _get_redis()
        if redis_client:
            try:
                redis_client.set(
                    f"cache:{key}",
                    json.dumps(cache_data),
                    ex=ttl_seconds  # Automatic expiration
                )
                logger.debug(f"Redis cache set for key: {key}")
                return True
            except Exception as exc:
                logger.warning(f"Redis set failed for {key}: {exc}, falling back to file cache")
        
        # Fallback to file cache
        cache_file = CACHE_DIR / f"{key}.json"
        
        try:
            with open(cache_file, "w") as f:
                json.dump(cache_data, f, indent=2)
            
            logger.debug(f"File cache set for key: {key}")
            return True
            
        except Exception as exc:
            logger.error(f"Failed to write cache for {key}: {exc}")
            return False
    
    @staticmethod
    def delete(key: str) -> bool:
        """
        Delete cached data.
        
        Args:
            key: Cache key to delete
            
        Returns:
            True if deleted, False if not found
        """
        deleted = False
        
        # Try Redis first
        redis_client = _get_redis()
        if redis_client:
            try:
                if redis_client.delete(f"cache:{key}"):
                    logger.debug(f"Redis cache deleted for key: {key}")
                    deleted = True
            except Exception as exc:
                logger.warning(f"Redis delete failed for {key}: {exc}")
        
        # Also try file cache
        cache_file = CACHE_DIR / f"{key}.json"
        
        try:
            if cache_file.exists():
                cache_file.unlink()
                logger.debug(f"File cache deleted for key: {key}")
                deleted = True
            return deleted
            
        except Exception as exc:
            logger.error(f"Failed to delete cache for {key}: {exc}")
            return deleted
    
    @staticmethod
    def clear_all() -> int:
        """
        Clear all cached data (Redis and files).
        
        Returns:
            Number of items deleted
        """
        count = 0
        
        # Clear Redis cache
        redis_client = _get_redis()
        if redis_client:
            try:
                keys = redis_client.keys("cache:*")
                if keys:
                    count += redis_client.delete(*keys)
                    logger.info(f"Cleared {len(keys)} keys from Redis cache")
            except Exception as exc:
                logger.error(f"Failed to clear Redis cache: {exc}")
        
        # Clear file cache
        try:
            for cache_file in CACHE_DIR.glob("*.json"):
                cache_file.unlink()
                count += 1
            logger.info(f"Cleared file cache")
            return count
            
        except Exception as exc:
            logger.error(f"Failed to clear file cache: {exc}")
            return count


# Convenience functions
def get_cached(key: str, max_age_minutes: int = 60) -> dict[str, Any] | None:
    """Get cached data (convenience function). Uses Redis if available, falls back to files."""
    return SharedCache.get(key, max_age_minutes)


def set_cached(key: str, data: dict[str, Any], ttl_seconds: int | None = None) -> bool:
    """Set cached data (convenience function). Uses Redis if available, falls back to files."""
    return SharedCache.set(key, data, ttl_seconds)
