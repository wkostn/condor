"""Test script for validate_setup routine.

Usage:
    docker exec hummingbird-condor-1 bash -c "cd /app && uv run python tests/routines/test_validate_setup.py"
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
from routines.validate_setup import run, Config
from telegram.ext import ContextTypes


async def test():
    """Test validate_setup with a mock candidate."""
    
    # Example candidate from high_vol_coin_levels
    config = Config(
        trading_pair="BTC-USDT",
        connector="binance_perpetual",
        bias="LONG",
        last_price=64250.0,
        pullback_level=64000.0,  # EMA
        breakout_level=64500.0,  # Recent high
        breakdown_level=63800.0,  # Recent low
        invalid_long_level=63600.0,  # 4H low
        invalid_short_level=64700.0,  # 4H high
        atr_pct=1.8,
        proximity_pct=1.5,  # Within 1.5% = "near"
        max_stop_pct=4.0,  # Max acceptable stop
    )
    
    # Mock context (minimal for testing)
    context = type('Context', (), {
        '_chat_id': 0,
        'user_data': {},
        'bot': None,
    })()
    
    print(f"Testing validate_setup for {config.trading_pair}...")
    print(f"Bias: {config.bias} | Price: ${config.last_price}")
    print(f"Pullback: ${config.pullback_level} | Breakout: ${config.breakout_level}")
    print("-" * 70)
    
    try:
        result = await run(config, context)
        print(result.text if hasattr(result, 'text') else str(result))
        
        if hasattr(result, 'table_data') and result.table_data:
            data = result.table_data[0]
            print(f"\n{'='*70}")
            print(f"DECISION: {data['decision']}")
            print(f"REASON: {data['reason']}")
            print(f"QUALITY: {data['quality_score']}/100")
            print(f"READY: {data['ready']}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test())
