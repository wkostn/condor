"""Test vpin_calc routine."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
from routines.vpin_calc import run, Config


async def test():
    context = type('Context', (), {'_chat_id': 0, 'user_data': {}, 'bot': None})()
    
    print("=" * 70)
    print("Testing vpin_calc routine")
    print("=" * 70)
    print()
    
    config = Config(
        trading_pairs=["BTC-USDT", "ETH-USDT", "SOL-USDT"],
        connector="hyperliquid_perpetual",
        num_buckets=50,
        bucket_volume_usd=1_000_000,
    )
    
    result = await run(config, context)
    
    if isinstance(result, str):
        print(f"Result: {result}")
    else:
        print(f"✓ Calculated VPIN for {len(result.table_data)} pairs")
        print(f"\n{result.text}")
    
    print()
    print("=" * 70)
    print("✓ Test complete")


if __name__ == "__main__":
    asyncio.run(test())
