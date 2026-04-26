"""Test list_available_pairs routine."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
from routines.list_available_pairs import run, Config


async def test():
    # Mock context
    context = type('Context', (), {
        '_chat_id': 0,
        'user_data': {},
        'bot': None,
    })()
    
    print("=" * 70)
    print("Testing list_available_pairs routine")
    print("=" * 70)
    print()
    
    # Test Hyperliquid
    print("Test 1: Hyperliquid USDT pairs")
    print("-" * 70)
    config = Config(exchange="hyperliquid", quote_asset="USDT")
    result = await run(config, context)
    
    if isinstance(result, str):
        print(f"Result (string): {result[:500]}")
    else:
        print(f"Result type: {type(result)}")
        print(f"Text: {result.text[:500] if result.text else 'None'}")
        print(f"Pairs count: {len(result.table_data) if result.table_data else 0}")
        if result.table_data:
            print(f"Sample pairs: {[p['trading_pair'] for p in result.table_data[:10]]}")
    
    print()
    print("=" * 70)
    print("✓ Test complete")


if __name__ == "__main__":
    asyncio.run(test())
