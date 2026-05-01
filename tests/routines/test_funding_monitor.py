"""Test funding_monitor routine."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
from routines.funding_monitor import run, Config


async def test():
    context = type('Context', (), {'_chat_id': 0, 'user_data': {}, 'bot': None})()
    
    print("=" * 70)
    print("Testing funding_monitor routine")
    print("=" * 70)
    print()
    
    config = Config(
        trading_pairs=["BTC-USDT", "ETH-USDT", "SOL-USDT"],
        high_funding_threshold=0.01,
        lookback_hours=24,
    )
    
    result = await run(config, context)
    
    if isinstance(result, str):
        print(f"Result: {result}")
    else:
        print(f"✓ Fetched derivatives data for {len(result.table_data)} pairs")
        print(f"\n{result.text}")
    
    print()
    print("=" * 70)
    print("✓ Test complete")


if __name__ == "__main__":
    asyncio.run(test())
