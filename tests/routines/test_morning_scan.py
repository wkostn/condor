"""Test script for morning_scan routine.

Usage:
    cd /app && uv run python test_morning_scan.py
"""

import asyncio
import logging
from datetime import datetime

# Mock context for testing
class MockContext:
    _chat_id = 0
    user_data = {}
    bot_data = {}
    
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}

async def main():
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 80)
    print("🌅 Testing morning_scan Routine")
    print("=" * 80)
    print()
    
    # Import after logging is configured
    from routines.morning_scan import run, Config
    
    # Create config
    config = Config(
        top_n=50,
        candidates=15,
        connector="binance_perpetual",
        interval="5m",
        max_records=72,
        min_volume_usd=25_000_000,
    )
    
    print(f"Configuration:")
    print(f"  - Scanning top {config.top_n} pairs by volume")
    print(f"  - Minimum volume: ${config.min_volume_usd:,.0f}")
    print(f"  - Returning top {config.candidates} candidates")
    print()
    
    # Run the routine
    start_time = datetime.utcnow()
    context = MockContext()
    
    try:
        result = await run(config, context)
        
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        
        print()
        print("=" * 80)
        print(f"✅ Routine completed in {elapsed:.2f} seconds")
        print("=" * 80)
        print()
        
        if isinstance(result, str):
            print(f"Result: {result}")
        else:
            print(result.text)
            print()
            print(f"Returned {len(result.table_data)} MarketState objects")
            print()
            
            if result.table_data:
                print("Top 5 Opportunities:")
                print("-" * 80)
                for idx, row in enumerate(result.table_data[:5], start=1):
                    print(
                        f"{idx}. {row['trading_pair']:12s} [{row['tier']:12s}] "
                        f"Score: {row['opportunity_score']:.3f} | "
                        f"Price: ${row['price']:.4f} | "
                        f"24h: {row['change_24h']:+.2f}% | "
                        f"Vol: ${row['volume_24h']/1e6:.1f}M"
                    )
    
    except Exception as exc:
        print(f"❌ Error: {exc}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
