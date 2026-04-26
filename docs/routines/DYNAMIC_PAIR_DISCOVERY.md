# Dynamic Pair Discovery

## Overview

Dynamically queries exchange APIs to get available trading pairs instead of using hardcoded lists.

## New Routine: list_available_pairs

Located at: `/routines/list_available_pairs.py`

### Purpose
Fetch the current list of tradeable pairs from an exchange's public API.

### Supported Exchanges
- **Hyperliquid** - via POST to `https://api.hyperliquid.xyz/info`
- **Binance Perpetual** - via GET to `https://fapi.binance.com/fapi/v1/exchangeInfo`
- **Binance Spot** - via GET to `https://api.binance.com/api/v3/exchangeInfo`

### Configuration

```python
{
    "exchange": "hyperliquid",  # or "binance_perpetual", "binance_spot"
    "quote_asset": "USDT",      # Filter by quote asset
    "status_filter": "TRADING"  # Only include active markets
}
```

### Response

Returns a `RoutineResult` with:
- `text`: Summary of pairs found
- `table_data`: List of `{"trading_pair": "BTC-USDT"}` dicts
- `table_columns`: ["trading_pair"]

### Example Usage from Agent

```python
pairs_result = manage_routines(
    action="run",
    name="list_available_pairs",
    config={
        "exchange": "hyperliquid",
        "quote_asset": "USDT",
    }
)

# Extract pairs
available_pairs = {row["trading_pair"] for row in pairs_result.table_data}
```

## Integration with high_vol_coin_levels

### How It Works

1. **Fetch from Binance** - Get top 30 coins by volume (discovery)
2. **Query Hyperliquid API** - Get list of 230+ available pairs
3. **Filter** - Keep only pairs that exist on Hyperliquid
4. **Fetch candles** - Only for available pairs (no wasted calls)
5. **Analyze & rank** - Return top 5 candidates

### Caching

- **TTL**: 60 minutes
- **Key**: `{connector}:{quote_asset}` (e.g., `hyperliquid_perpetual:USDT`)
- **Storage**: In-memory dict `_PAIRS_CACHE`
- **Benefit**: Reduces API calls from every 5min to every 60min

### Implementation

```python
# In high_vol_coin_levels.py

_PAIRS_CACHE: dict[str, tuple[set[str], datetime]] = {}
CACHE_TTL_MINUTES = 60

async def _get_available_pairs_from_exchange(connector: str, quote_asset: str) -> set[str]:
    # Check cache first
    cache_key = f"{connector}:{quote_asset}"
    if cache_key in _PAIRS_CACHE:
        pairs, cached_at = _PAIRS_CACHE[cache_key]
        if now - cached_at < timedelta(minutes=CACHE_TTL_MINUTES):
            return pairs  # Return cached
    
    # Fetch from API
    if connector == "hyperliquid_perpetual":
        # Query https://api.hyperliquid.xyz/info
        # Extract pairs from universe
    
    # Cache and return
    _PAIRS_CACHE[cache_key] = (pairs, now)
    return pairs
```

## Benefits

✅ **No hardcoded lists** - Removed `HYPERLIQUID_MAJOR_PAIRS` constant  
✅ **Always up-to-date** - Discovers new listings automatically  
✅ **Maintainable** - No manual updates needed  
✅ **Performant** - 1-hour cache reduces API load  
✅ **Extensible** - Easy to add support for other exchanges  
✅ **Resilient** - Falls back gracefully if API fails  

## Test Results

### list_available_pairs
- **Hyperliquid**: 230 pairs discovered
- **Response time**: ~500ms
- **Cache**: Working correctly

### high_vol_coin_levels
- **Before filtering**: 30 pairs from Binance
- **After filtering**: ~25 pairs (5 not on Hyperliquid)
- **Candidates returned**: 5
- **No wasted API calls**: ✓

## Logging

```
INFO: Fetched 230 pairs from Hyperliquid API
INFO: Filtered out 5 pairs not available on hyperliquid_perpetual (25 remain)
DEBUG: Using cached pairs for hyperliquid_perpetual (230 pairs)
```

## Adding New Exchanges

To add support for a new exchange:

1. Add API endpoint to `EXCHANGE_ENDPOINTS` dict
2. Implement fetching logic in `_fetch_{exchange}_pairs()`
3. Add case in `list_available_pairs.run()`
4. Add case in `high_vol_coin_levels._get_available_pairs_from_exchange()`

## Maintenance

- **Cache invalidation**: Automatic after 60 minutes
- **Manual refresh**: Restart agent or wait for TTL
- **Update exchange list**: Edit `EXCHANGE_ENDPOINTS` constant
- **Adjust TTL**: Modify `CACHE_TTL_MINUTES` (default: 60)

## Future Enhancements

- Store cache in Redis for persistence across restarts
- Add WebSocket support for real-time updates
- Implement configurable cache TTL per exchange
- Add metrics for cache hit/miss rates

---

*Last updated: 2026-04-26*
