"""Test news_reader routine."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
from routines.news_reader import run, Config


async def test():
    context = type('Context', (), {'_chat_id': 0, 'user_data': {}, 'bot': None})()
    
    print("=" * 70)
    print("Testing news_reader routine")
    print("=" * 70)
    print()
    
    config = Config(
        assets=["BTC", "ETH", "SOL"],
        lookback_hours=48,
        sources=["cointelegraph", "coindesk", "coinmarketcap"],
    )
    
    result = await run(config, context)
    
    if isinstance(result, str):
        print(f"Result: {result}")
    else:
        print(f"✓ Found {len(result.table_data)} news articles")
        print(f"\n{result.text}")
    
    print()
    print("=" * 70)
    print("✓ Test complete")


if __name__ == "__main__":
    asyncio.run(test())
