"""Test connectors attribute."""

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
    
    print("Checking connectors attribute...")
    print(f"Type: {type(client.connectors)}")
    print(f"Methods: {[m for m in dir(client.connectors) if not m.startswith('_')]}")
    
    # Try getting connector info
    try:
        info = await client.connectors.get_connector_info(connector_name="hyperliquid_perpetual")
        print(f"Connector info: {info}")
    except Exception as e:
        print(f"get_connector_info failed: {e}")
    
    # Try listing connectors
    try:
        connectors = await client.connectors.get_connectors()
        print(f"Connectors: {connectors}")
    except Exception as e:
        print(f"get_connectors failed: {e}")


if __name__ == "__main__":
    asyncio.run(test())
