"""Test high_vol_coin_levels with dynamic pair discovery."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncio
from trading_agents.high_vol_levels_5x.routines.high_vol_coin_levels import run, Config


async def test():
    context = type('Context', (), {'_chat_id': 0, 'user_data': {}, 'bot': None})()
    
    print("=" * 70)
    print("Testing high_vol_coin_levels with dynamic pair discovery")
    print("=" * 70)
    print()
    
    # Test 1: First call (should fetch from API)
    print("Test 1: First call (should fetch pairs from Hyperliquid API)")
    print("-" * 70)
    config = Config(connector="hyperliquid_perpetual", top_n=30, candidates=5)
    result = await run(config, context)
    
    if isinstance(result, str):
        print(f"Result (string): {result}")
    else:
        print(f"✓ Found {len(result.table_data)} candidates")
        for i, candidate in enumerate(result.table_data, 1):
            print(f"  {i}. {candidate['trading_pair']} ({candidate['bias']}) - Score: {candidate['score']}")
    
    print()
    
    # Test 2: Second call immediately (should use cache)
    print("Test 2: Second call (should use cached pairs)")
    print("-" * 70)
    result2 = await run(config, context)
    
    if isinstance(result2, str):
        print(f"Result (string): {result2}")
    else:
        print(f"✓ Found {len(result2.table_data)} candidates (from cache)")
    
    print()
    print("=" * 70)
    print("✓ Test complete - check logs for 'Fetched' vs 'Using cached'")


if __name__ == "__main__":
    asyncio.run(test())
