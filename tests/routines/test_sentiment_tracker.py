"""Test sentiment_tracker routine."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
from routines.sentiment_tracker import run, Config


async def test():
    context = type('Context', (), {'_chat_id': 0, 'user_data': {}, 'bot': None})()
    
    print("=" * 70)
    print("Testing sentiment_tracker routine")
    print("=" * 70)
    print()
    
    config = Config(
        assets=["BTC", "ETH", "SOL"],
        lookback_hours=48,
        connector="binance_perpetual",
    )
    
    result = await run(config, context)
    
    if isinstance(result, str):
        print(f"Result: {result}")
    else:
        print(f"✓ Analyzed sentiment for {len(result.table_data)} assets")
        print(f"\n{result.text}")
    
    print()
    print("=" * 70)
    print("✓ Test complete")


if __name__ == "__main__":
    asyncio.run(test())
