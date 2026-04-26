"""Test script for tech_overlay routine.

Usage:
    cd /app && uv run python test_tech_overlay.py
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
    print("📊 Testing tech_overlay Routine")
    print("=" * 80)
    print()
    
    # Import after logging is configured
    from config_manager import get_client
    from routines.tech_overlay import compute_technical_indicators, Config
    
    # Get client
    context = MockContext()
    client = await get_client(context._chat_id, context=context)
    
    if not client:
        print("❌ No Hummingbot client available")
        return 1
    
    # Test with BTC and ETH
    test_pairs = [
        ("BTC-USDT", "binance_perpetual"),
        ("ETH-USDT", "binance_perpetual"),
    ]
    
    for trading_pair, connector in test_pairs:
        print(f"\n{'='*80}")
        print(f"Testing {trading_pair}")
        print(f"{'='*80}\n")
        
        # Fetch candles
        try:
            result = await client.market_data.get_candles(
                connector_name=connector,
                trading_pair=trading_pair,
                interval="5m",
                max_records=250,
            )
            
            if isinstance(result, dict):
                candles = result.get("data", [])
            elif isinstance(result, list):
                candles = result
            else:
                print(f"❌ Unexpected result type: {type(result)}")
                continue
            
            if not candles:
                print(f"❌ No candles returned for {trading_pair}")
                continue
            
            print(f"✅ Fetched {len(candles)} candles")
            
            # Compute indicators
            config = Config()
            indicators = compute_technical_indicators(candles, config)
            
            if not indicators:
                print(f"❌ Failed to compute indicators for {trading_pair}")
                continue
            
            # Display results
            print("\n📈 Technical Indicators:")
            print(f"  {'Indicator':<25} {'Value':<15}")
            print(f"  {'-'*40}")
            print(f"  {'RSI (4H)':<25} {indicators.rsi_4h:<15.2f}")
            print(f"  {'RSI (1D)':<25} {indicators.rsi_1d:<15.2f}")
            print(f"  {'ADX':<25} {indicators.adx:<15.2f}")
            print(f"  {'Trend Direction':<25} {indicators.trend_direction:<15}")
            print(f"  {'Bollinger Position':<25} {indicators.bollinger_position:<15.3f}")
            print(f"  {'ATR %':<25} {indicators.atr_percent:<15.3f}")
            
            if indicators.ema_20:
                print(f"  {'EMA 20':<25} ${indicators.ema_20:<14.2f}")
            if indicators.ema_50:
                print(f"  {'EMA 50':<25} ${indicators.ema_50:<14.2f}")
            if indicators.ema_200:
                print(f"  {'EMA 200':<25} ${indicators.ema_200:<14.2f}")
            
            print(f"\n  Support Levels:")
            for i, level in enumerate(indicators.support_levels, 1):
                print(f"    S{i}: ${level:.2f}")
            
            print(f"\n  Resistance Levels:")
            for i, level in enumerate(indicators.resistance_levels, 1):
                print(f"    R{i}: ${level:.2f}")
            
            # Interpretation
            print(f"\n💡 Interpretation:")
            
            if indicators.rsi_4h < 30:
                print(f"  • RSI shows OVERSOLD conditions ({indicators.rsi_4h:.1f})")
            elif indicators.rsi_4h > 70:
                print(f"  • RSI shows OVERBOUGHT conditions ({indicators.rsi_4h:.1f})")
            else:
                print(f"  • RSI neutral ({indicators.rsi_4h:.1f})")
            
            if indicators.adx > 25:
                print(f"  • Strong trend (ADX {indicators.adx:.1f})")
            elif indicators.adx > 20:
                print(f"  • Developing trend (ADX {indicators.adx:.1f})")
            else:
                print(f"  • Weak/ranging market (ADX {indicators.adx:.1f})")
            
            if indicators.trend_direction == "bullish":
                print(f"  • Bullish trend confirmed")
            elif indicators.trend_direction == "bearish":
                print(f"  • Bearish trend confirmed")
            else:
                print(f"  • No clear trend (neutral)")
            
            if indicators.bollinger_position > 0.8:
                print(f"  • Near upper Bollinger Band (possible reversal)")
            elif indicators.bollinger_position < -0.8:
                print(f"  • Near lower Bollinger Band (possible reversal)")
            
        except Exception as exc:
            print(f"❌ Error testing {trading_pair}: {exc}")
            import traceback
            traceback.print_exc()
            continue
    
    print(f"\n{'='*80}")
    print("✅ Testing complete")
    print(f"{'='*80}\n")
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
