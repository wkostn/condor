"""Test smallcap_screener routine."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
from routines.smallcap_screener import run, Config


async def test():
    context = type('Context', (), {'_chat_id': 0, 'user_data': {}, 'bot': None})()
    
    print("=" * 70)
    print("Testing smallcap_screener routine")
    print("=" * 70)
    print()
    
    config = Config(
        max_market_cap=100_000_000,
        min_market_cap=1_000_000,
        min_volume_24h=100_000,
        top_n=50,
        candidates=5,
        connector="binance_perpetual",
    )
    
    result = await run(config, context)
    
    if isinstance(result, str):
        print(f"Result: {result}")
    else:
        print(f"✓ Found {len(result.table_data)} small-cap opportunities")
        print(f"\n{result.text}")
    
    print()
    print("=" * 70)
    print("✓ Test complete")


if __name__ == "__main__":
    asyncio.run(test())
