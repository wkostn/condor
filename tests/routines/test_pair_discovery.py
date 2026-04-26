"""Test available pairs discovery from Hyperliquid."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
from config_manager import get_client


async def test_get_pairs():
    """Test getting available pairs from Hyperliquid."""
    
    # Mock context
    context = type('Context', (), {
        '_chat_id': 0,
        'user_data': {},
        'bot': None,
    })()
    
    print("=" * 70)
    print("Testing available pairs discovery on hyperliquid_perpetual")
    print("=" * 70)
    
    client = await get_client(context._chat_id, context=context)
    if not client:
        print("❌ No client available")
        return
    
    print("✓ Client obtained")
    print()
    
    # Test method 1: get_trading_pairs
    print("Method 1: client.market_data.get_trading_pairs()")
    try:
        result = await client.market_data.get_trading_pairs(connector_name="hyperliquid_perpetual")
        print(f"  Result type: {type(result)}")
        if isinstance(result, list):
            print(f"  Found {len(result)} pairs")
            print(f"  Sample pairs: {result[:10]}")
        elif isinstance(result, dict):
            print(f"  Dict keys: {result.keys()}")
            if "data" in result:
                print(f"  Found {len(result['data'])} pairs in data field")
                print(f"  Sample pairs: {result['data'][:10]}")
        else:
            print(f"  Unexpected format: {result}")
    except AttributeError as e:
        print(f"  ❌ Method not available: {e}")
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    print()
    
    # Test method 2: get_markets
    print("Method 2: client.get_markets()")
    try:
        result = await client.get_markets(connector_name="hyperliquid_perpetual")
        print(f"  Result type: {type(result)}")
        if isinstance(result, list):
            print(f"  Found {len(result)} markets")
            if result:
                print(f"  Sample market: {result[0]}")
                pairs = [m.get("trading_pair") for m in result if isinstance(m, dict)]
                print(f"  Extracted {len([p for p in pairs if p])} pairs")
                print(f"  Sample pairs: {[p for p in pairs if p][:10]}")
        else:
            print(f"  Unexpected format: {result}")
    except AttributeError as e:
        print(f"  ❌ Method not available: {e}")
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    print()
    
    # Test method 3: check what's actually available on client
    print("Method 3: Inspect client attributes")
    print(f"  client type: {type(client)}")
    print(f"  client attributes: {[attr for attr in dir(client) if not attr.startswith('_')][:20]}")
    if hasattr(client, 'market_data'):
        print(f"  market_data type: {type(client.market_data)}")
        print(f"  market_data methods: {[attr for attr in dir(client.market_data) if not attr.startswith('_') and callable(getattr(client.market_data, attr))]}")


if __name__ == "__main__":
    asyncio.run(test_get_pairs())
