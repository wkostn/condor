"""Correlation checker - analyzes correlation between trading pairs to avoid overexposure."""

from __future__ import annotations

import logging
import statistics
from typing import Any

from pydantic import BaseModel, Field
from telegram.ext import ContextTypes

from config_manager import get_client
from routines.base import RoutineResult

logger = logging.getLogger(__name__)


class Config(BaseModel):
    """Correlation checker configuration."""
    
    trading_pair_a: str = Field(default="BTC-USD", description="First trading pair (e.g., BTC-USD)")
    trading_pair_b: str = Field(default="ETH-USD", description="Second trading pair (e.g., ETH-USD)")
    connector: str = Field(default="hyperliquid_perpetual", description="Exchange connector")
    lookback_hours: int = Field(default=24, description="Hours of data for correlation (4-168)")
    interval: str = Field(default="1h", description="Candle interval (1m, 5m, 15m, 1h, 4h)")


def _calculate_correlation(returns_a: list[float], returns_b: list[float]) -> float:
    """Calculate Pearson correlation coefficient."""
    if len(returns_a) != len(returns_b) or len(returns_a) < 2:
        return 0.0
    
    mean_a = statistics.mean(returns_a)
    mean_b = statistics.mean(returns_b)
    
    numerator = sum((a - mean_a) * (b - mean_b) for a, b in zip(returns_a, returns_b))
    
    variance_a = sum((a - mean_a) ** 2 for a in returns_a)
    variance_b = sum((b - mean_b) ** 2 for b in returns_b)
    
    denominator = (variance_a * variance_b) ** 0.5
    
    if denominator == 0:
        return 0.0
    
    return numerator / denominator


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    """
    Check correlation between two trading pairs.
    
    Returns:
        dict with:
        - correlation: Pearson correlation coefficient (-1 to 1)
        - interpretation: "HIGH_POSITIVE" / "MODERATE_POSITIVE" / "LOW" / "MODERATE_NEGATIVE" / "HIGH_NEGATIVE"
        - recommendation: "DIVERSIFIED" / "NEUTRAL" / "REDUNDANT"
        - both_long_risk: Risk level if both pairs are longed
        - both_short_risk: Risk level if both pairs are shorted
    """
    
    client = await get_client(context._chat_id, context=context)
    if not client:
        return "No server available"
    
    # Fetch candles for both pairs
    try:
        candles_a_result = await client.market_data.get_candles(
            connector_name=config.connector,
            trading_pair=config.trading_pair_a,
            interval=config.interval,
            max_records=config.lookback_hours,
        )
        
        candles_b_result = await client.market_data.get_candles(
            connector_name=config.connector,
            trading_pair=config.trading_pair_b,
            interval=config.interval,
            max_records=config.lookback_hours,
        )
    except Exception as exc:
        return f"Error fetching candles: {exc}"
    
    if not candles_a_result or not candles_b_result:
        return "Error: Could not fetch candles for one or both pairs"
    
    # Calculate returns
    closes_a = [c["close"] for c in candles_a_result[-config.lookback_hours:]]
    closes_b = [c["close"] for c in candles_b_result[-config.lookback_hours:]]
    
    if len(closes_a) < 2 or len(closes_b) < 2:
        return "Error: Insufficient candle data"
    
    # Match lengths (use shorter)
    min_len = min(len(closes_a), len(closes_b))
    closes_a = closes_a[-min_len:]
    closes_b = closes_b[-min_len:]
    
    returns_a = [(closes_a[i] - closes_a[i-1]) / closes_a[i-1] for i in range(1, len(closes_a))]
    returns_b = [(closes_b[i] - closes_b[i-1]) / closes_b[i-1] for i in range(1, len(closes_b))]
    
    correlation = _calculate_correlation(returns_a, returns_b)
    
    # Interpret correlation
    abs_corr = abs(correlation)
    if abs_corr >= 0.7:
        strength = "HIGH"
    elif abs_corr >= 0.4:
        strength = "MODERATE"
    else:
        strength = "LOW"
    
    direction = "POSITIVE" if correlation >= 0 else "NEGATIVE"
    interpretation = f"{strength}_{direction}" if strength != "LOW" else "LOW"
    
    # Recommendation
    if abs_corr < 0.3:
        recommendation = "DIVERSIFIED"  # Good diversification
        both_long_risk = "LOW"
        both_short_risk = "LOW"
    elif abs_corr < 0.6:
        recommendation = "NEUTRAL"  # Some correlation but acceptable
        both_long_risk = "MODERATE" if correlation > 0 else "LOW"
        both_short_risk = "MODERATE" if correlation > 0 else "LOW"
    else:
        recommendation = "REDUNDANT"  # Too correlated, avoid both
        both_long_risk = "HIGH" if correlation > 0 else "LOW"
        both_short_risk = "HIGH" if correlation > 0 else "LOW"
    
    result = {
        "pair_a": config.trading_pair_a,
        "pair_b": config.trading_pair_b,
        "correlation": round(correlation, 3),
        "interpretation": interpretation,
        "recommendation": recommendation,
        "both_long_risk": both_long_risk,
        "both_short_risk": both_short_risk,
        "sample_size": len(returns_a),
    }
    
    summary = (
        f"Correlation Analysis:\n"
        f"• {config.trading_pair_a} vs {config.trading_pair_b}\n"
        f"• Correlation: {correlation:.3f} ({interpretation})\n"
        f"• Recommendation: {recommendation}\n"
        f"• Both LONG risk: {both_long_risk}\n"
        f"• Both SHORT risk: {both_short_risk}\n"
        f"• Sample: {len(returns_a)} {config.interval} candles\n"
    )
    
    logger.info(f"Correlation {config.trading_pair_a} vs {config.trading_pair_b}: {correlation:.3f}")
    
    return RoutineResult(
        text=summary,
        table_data=[result],
        table_columns=list(result.keys()),
    )
