"""Test get_trading_rules to find available pairs."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
from config_manager import get_client


async def test():
    context = type('Context', (), {'_chat_id': 0, 'user_data': {}, 'bot': None})()
    
    client = await get_client(context._chat_id, context=context)
    if not client:
        print("No client")
        return
    
    print("Testing get_trading_rules...")
    try:
        rules = await client.connectors.get_trading_rules(connector_name="hyperliquid_perpetual")
        print(f"Result type: {type(rules)}")
        
        if isinstance(rules, dict):
            print(f"Dict keys: {rules.keys()}")
            if "trading_pairs" in rules:
                pairs = rules["trading_pairs"]
                print(f"Found {len(pairs)} trading pairs")
                print(f"Sample pairs: {list(pairs.keys())[:10] if isinstance(pairs, dict) else pairs[:10]}")
            else:
                # Maybe the pairs are the dict keys themselves
                print(f"Top-level keys (might be pairs): {list(rules.keys())[:20]}")
        elif isinstance(rules, list):
            print(f"Found {len(rules)} items")
            print(f"Sample items: {rules[:3]}")
        else:
            print(f"Unexpected type: {rules}")
            
    except Exception as e:
        print(f"get_trading_rules failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test())
