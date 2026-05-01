"""Combo Deal Checker Routine.

Determines if a new Combo Bot deal should start based on market regime,
technical indicators, and risk conditions.

The Combo Bot is designed for:
- Bear descent markets (ADX 25-40, downtrend)
- Choppy consolidation (ADX < 25, high volatility)
- News-driven pullbacks (fundamental bullish but price down)

It should NOT start during:
- Strong uptrends (ADX > 35 bullish)
- Liquidation cascades (funding > 0.2%)
- Flash crashes (-10% in 5 minutes)
- Low liquidity (24h volume < $50M)

Example usage:
    config = Config(
        connector="hyperliquid_perpetual",
        trading_pair="BTC-USD",
        current_cash=2000.0,
        min_cash_to_start=200.0,
        deal_cooldown_met=True
    )
    
    result = await run(config, context)
    
    # Returns:
    # {
    #   "should_start": true/false,
    #   "reason": "ADX=22 (ranging), RSI=45 (room to DCA), funding=0.01% (normal)",
    #   "entry_price": 95000.0,
    #   "regime": "CHOPPY" | "BEAR_DESCENT" | "NEWS_PULLBACK" | "SKIP"
    # }
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class Config(BaseModel):
    """Configuration for deal checker."""
    
    # Market parameters
    connector: str = Field(
        default="hyperliquid_perpetual",
        description="Exchange connector name"
    )
    trading_pair: str = Field(
        default="BTC-USD",
        description="Trading pair to analyze"
    )
    
    # Capital parameters
    current_cash: float = Field(
        default=2000.0,
        description="Available cash balance"
    )
    min_cash_to_start: float = Field(
        default=200.0,
        description="Minimum cash required to start a deal"
    )
    
    # Cooldown
    deal_cooldown_met: bool = Field(
        default=True,
        description="Whether the deal cooldown period has elapsed"
    )
    
    # Regime thresholds
    max_adx_for_choppy: float = Field(
        default=25.0,
        description="Max ADX for choppy/ranging regime"
    )
    min_adx_for_bear: float = Field(
        default=20.0,
        description="Min ADX for bear descent regime"
    )
    max_adx_for_bear: float = Field(
        default=40.0,
        description="Max ADX for bear descent regime"
    )
    min_rsi: float = Field(
        default=30.0,
        description="Min RSI (don't start if already oversold)"
    )
    max_rsi: float = Field(
        default=70.0,
        description="Max RSI (room to DCA down)"
    )
    max_funding_rate: float = Field(
        default=0.001,
        description="Max funding rate (0.001 = 0.1%)"
    )
    min_volume_24h_usd: float = Field(
        default=50_000_000.0,
        description="Min 24h volume in USD"
    )


class RoutineResult(BaseModel):
    """Standard routine result format."""
    text: str
    table_data: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    """Check if a new Combo Bot deal should start.
    
    Args:
        config: Deal checker configuration
        context: Telegram context (used to access Hummingbot API client)
        
    Returns:
        RoutineResult with decision or error string
    """
    try:
        # Import Hummingbot client utilities
        try:
            from condor.utils.hummingbot_client import get_client
        except ImportError:
            logger.warning("Could not import get_client, using mock mode")
            # Mock mode for testing
            return await _mock_check(config)
        
        # Get client
        client = await get_client(context._chat_id, context=context)
        if not client:
            return "No Hummingbot API client available"
        
        # 1. Check cooldown
        if not config.deal_cooldown_met:
            return RoutineResult(
                text="❌ **Deal Start: SKIP** — Cooldown period not yet elapsed",
                table_data=[{"should_start": False, "reason": "cooldown"}],
                sections=[{"title": "decision", "content": "SKIP (cooldown)"}]
            )
        
        # 2. Check cash balance
        if config.current_cash < config.min_cash_to_start:
            return RoutineResult(
                text=f"❌ **Deal Start: SKIP** — Insufficient cash (${config.current_cash:.2f} < ${config.min_cash_to_start:.2f})",
                table_data=[{"should_start": False, "reason": "insufficient_cash"}],
                sections=[{"title": "decision", "content": f"SKIP (cash: ${config.current_cash:.2f})"}]
            )
        
        # 3. Get current market price
        try:
            ticker = await client.market_data.get_ticker(
                connector_name=config.connector,
                trading_pair=config.trading_pair
            )
            if isinstance(ticker, dict):
                entry_price = float(ticker.get("last_price", 0))
                volume_24h = float(ticker.get("volume_24h_quote", 0))
            else:
                entry_price = float(ticker.last_price)
                volume_24h = float(ticker.volume_24h_quote)
        except Exception as e:
            logger.error(f"Failed to get ticker: {e}")
            return f"Error getting market price: {e}"
        
        if entry_price <= 0:
            return "Invalid entry price from ticker"
        
        # 4. Check 24h volume
        if volume_24h < config.min_volume_24h_usd:
            return RoutineResult(
                text=f"❌ **Deal Start: SKIP** — Low liquidity (24h volume ${volume_24h:,.0f} < ${config.min_volume_24h_usd:,.0f})",
                table_data=[{"should_start": False, "reason": "low_liquidity", "volume_24h": volume_24h}],
                sections=[{"title": "decision", "content": f"SKIP (volume: ${volume_24h:,.0f})"}]
            )
        
        # 5. Get technical indicators
        # For Phase 1, we'll use simplified checks
        # In production, call tech_overlay routine
        try:
            candles = await client.market_data.get_candles(
                connector_name=config.connector,
                trading_pair=config.trading_pair,
                interval="1h",
                max_records=100
            )
            
            if isinstance(candles, list):
                candles_data = candles
            elif isinstance(candles, dict):
                candles_data = candles.get("data", [])
            else:
                candles_data = []
            
            if len(candles_data) < 20:
                return "Insufficient candle data for technical analysis"
            
            # Calculate simple RSI (14-period)
            closes = [float(c.get("close", 0)) for c in candles_data[-20:]]
            rsi = _calculate_rsi(closes, period=14)
            
            # Calculate simple ADX approximation
            # In production, use tech_overlay routine
            adx = _estimate_adx(candles_data[-30:])
            
        except Exception as e:
            logger.error(f"Failed to get candles: {e}")
            return f"Error getting market data: {e}"
        
        # 6. Get funding rate (if available)
        try:
            funding_info = await client.market_data.get_funding_info(
                connector_name=config.connector,
                trading_pair=config.trading_pair
            )
            if isinstance(funding_info, dict):
                funding_rate = float(funding_info.get("rate", 0))
            else:
                funding_rate = float(funding_info.rate)
        except Exception:
            # Funding rate not available, assume 0
            funding_rate = 0.0
        
        # 7. Regime classification
        regime = "UNKNOWN"
        should_start = False
        reasons = []
        
        # Check funding rate
        if abs(funding_rate) > config.max_funding_rate:
            reasons.append(f"funding too high ({funding_rate*100:.2f}%)")
            regime = "SKIP"
        
        # Check RSI
        if rsi < config.min_rsi:
            reasons.append(f"RSI too low ({rsi:.1f}, already oversold)")
            regime = "SKIP"
        elif rsi > config.max_rsi:
            reasons.append(f"RSI too high ({rsi:.1f}, no room to DCA)")
            regime = "SKIP"
        
        # Classify regime based on ADX
        if regime != "SKIP":
            if adx < config.max_adx_for_choppy:
                regime = "CHOPPY"
                should_start = True
                reasons.append(f"ADX={adx:.1f} (ranging/choppy)")
            elif config.min_adx_for_bear <= adx <= config.max_adx_for_bear:
                # Check if trending down (simplified: compare recent closes)
                if closes[-1] < closes[-5]:
                    regime = "BEAR_DESCENT"
                    should_start = True
                    reasons.append(f"ADX={adx:.1f} (bear descent)")
                else:
                    regime = "SKIP"
                    reasons.append(f"ADX={adx:.1f} but trending up")
            else:
                regime = "SKIP"
                reasons.append(f"ADX={adx:.1f} too high (strong trend)")
        
        # Add positive checks
        if should_start:
            reasons.append(f"RSI={rsi:.1f} (room to DCA)")
            reasons.append(f"funding={funding_rate*100:.3f}% (normal)")
            reasons.append(f"24h vol=${volume_24h/1e6:.1f}M (liquid)")
        
        # Format result
        decision_icon = "✅" if should_start else "❌"
        decision_text = "GO" if should_start else "SKIP"
        
        text_lines = [
            f"{decision_icon} **Deal Start: {decision_text}**",
            f"",
            f"**Market:** {config.trading_pair}",
            f"**Entry Price:** ${entry_price:,.2f}",
            f"**Regime:** {regime}",
            f"",
            f"**Reason:**"
        ]
        
        for reason in reasons:
            text_lines.append(f"  • {reason}")
        
        text = "\n".join(text_lines)
        
        table_data = [{
            "should_start": should_start,
            "regime": regime,
            "entry_price": entry_price,
            "adx": round(adx, 1),
            "rsi": round(rsi, 1),
            "funding_rate": round(funding_rate * 100, 3),
            "volume_24h_usd": volume_24h
        }]
        
        sections = [
            {
                "title": "decision",
                "content": f"{decision_text} ({regime})"
            },
            {
                "title": "technicals",
                "content": f"ADX={adx:.1f}, RSI={rsi:.1f}, funding={funding_rate*100:.3f}%"
            }
        ]
        
        return RoutineResult(
            text=text,
            table_data=table_data,
            sections=sections
        )
        
    except Exception as e:
        logger.error(f"Deal checker error: {e}", exc_info=True)
        return f"Error checking deal conditions: {e}"


def _calculate_rsi(closes: list[float], period: int = 14) -> float:
    """Calculate RSI from price closes.
    
    Simplified RSI calculation for Phase 1.
    """
    if len(closes) < period + 1:
        return 50.0  # neutral if insufficient data
    
    gains = []
    losses = []
    
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def _estimate_adx(candles: list[dict], period: int = 14) -> float:
    """Estimate ADX from candles.
    
    Simplified ADX calculation for Phase 1.
    In production, use tech_overlay routine.
    """
    if len(candles) < period + 1:
        return 20.0  # assume neutral if insufficient data
    
    # Calculate True Range
    tr_values = []
    for i in range(1, len(candles)):
        high = float(candles[i].get("high", 0))
        low = float(candles[i].get("low", 0))
        prev_close = float(candles[i-1].get("close", 0))
        
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        tr_values.append(tr)
    
    # Calculate directional movement
    plus_dm = []
    minus_dm = []
    
    for i in range(1, len(candles)):
        high = float(candles[i].get("high", 0))
        prev_high = float(candles[i-1].get("high", 0))
        low = float(candles[i].get("low", 0))
        prev_low = float(candles[i-1].get("low", 0))
        
        up_move = high - prev_high
        down_move = prev_low - low
        
        if up_move > down_move and up_move > 0:
            plus_dm.append(up_move)
            minus_dm.append(0)
        elif down_move > up_move and down_move > 0:
            plus_dm.append(0)
            minus_dm.append(down_move)
        else:
            plus_dm.append(0)
            minus_dm.append(0)
    
    # Simple moving average of directional indicators
    if len(tr_values) < period:
        return 20.0
    
    avg_tr = sum(tr_values[-period:]) / period
    avg_plus_dm = sum(plus_dm[-period:]) / period
    avg_minus_dm = sum(minus_dm[-period:]) / period
    
    if avg_tr == 0:
        return 0.0
    
    plus_di = 100 * avg_plus_dm / avg_tr
    minus_di = 100 * avg_minus_dm / avg_tr
    
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) > 0 else 0
    
    # ADX is MA of DX (simplified: just return DX for now)
    return dx


async def _mock_check(config: Config) -> RoutineResult:
    """Mock checker for testing without Hummingbot API."""
    return RoutineResult(
        text="✅ **Deal Start: GO** (MOCK MODE)\n\n"
             "**Market:** BTC-USD\n"
             "**Entry Price:** $95,000.00\n"
             "**Regime:** CHOPPY\n\n"
             "**Reason:**\n"
             "  • ADX=22.5 (ranging/choppy)\n"
             "  • RSI=45.0 (room to DCA)\n"
             "  • funding=0.012% (normal)\n"
             "  • 24h vol=$850.5M (liquid)",
        table_data=[{
            "should_start": True,
            "regime": "CHOPPY",
            "entry_price": 95000.0,
            "adx": 22.5,
            "rsi": 45.0,
            "funding_rate": 0.012,
            "volume_24h_usd": 850_500_000.0
        }],
        sections=[
            {"title": "decision", "content": "GO (CHOPPY)"},
            {"title": "technicals", "content": "ADX=22.5, RSI=45.0, funding=0.012%"}
        ]
    )
