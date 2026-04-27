"""Liquidity checker - verifies sufficient liquidity for safe entry and exit."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field
from telegram.ext import ContextTypes

from config_manager import get_client
from routines.base import RoutineResult

logger = logging.getLogger(__name__)


class Config(BaseModel):
    """Liquidity checker configuration."""
    
    trading_pair: str = Field(description="Trading pair to check (e.g., BTC-USD)")
    connector: str = Field(default="hyperliquid_perpetual", description="Exchange connector")
    position_size_usd: float = Field(description="Intended position size in USD")
    lookback_hours: int = Field(default=24, description="Hours to analyze (4-48)")
    min_volume_multiple: float = Field(default=50.0, description="Position must be < X% of avg volume")


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    """
    Check if there's sufficient liquidity for the intended position size.
    
    Returns:
        dict with:
        - avg_volume_usd: Average hourly volume in USD
        - position_as_pct_volume: Position size as % of avg volume
        - liquidity_rating: "EXCELLENT" / "GOOD" / "ACCEPTABLE" / "POOR" / "INADEQUATE"
        - recommendation: "SAFE" / "PROCEED_WITH_CAUTION" / "AVOID"
        - suggested_max_size: Maximum safe position size
        - slippage_risk: "LOW" / "MODERATE" / "HIGH"
    """
    
    client = await get_client(context._chat_id, context=context)
    if not client:
        return "No server available"
    
    # Fetch recent candles to analyze volume
    try:
        candles = await client.market_data.get_candles(
            connector_name=config.connector,
            trading_pair=config.trading_pair,
            interval="1h",
            max_records=config.lookback_hours,
        )
    except Exception as exc:
        return f"Error fetching candles for {config.trading_pair}: {exc}"
    
    if not candles or len(candles) < 4:
        return f"Error: Insufficient candle data for {config.trading_pair}"
    
    # Use recent data
    recent_candles = candles[-config.lookback_hours:] if len(candles) >= config.lookback_hours else candles
    
    # Calculate average volume (assume volume is in quote currency - USD)
    volumes = [float(c["volume"]) * float(c["close"]) for c in recent_candles]
    avg_volume_usd = sum(volumes) / len(volumes) if volumes else 0.0
    
    if avg_volume_usd <= 0:
        return f"Error: No volume data available for {config.trading_pair}"
    
    # Calculate position as % of average volume
    position_as_pct_volume = (config.position_size_usd / avg_volume_usd) * 100
    
    # Determine liquidity rating
    if position_as_pct_volume < 0.5:
        liquidity_rating = "EXCELLENT"
        recommendation = "SAFE"
        slippage_risk = "LOW"
    elif position_as_pct_volume < 2.0:
        liquidity_rating = "GOOD"
        recommendation = "SAFE"
        slippage_risk = "LOW"
    elif position_as_pct_volume < 5.0:
        liquidity_rating = "ACCEPTABLE"
        recommendation = "PROCEED_WITH_CAUTION"
        slippage_risk = "MODERATE"
    elif position_as_pct_volume < 10.0:
        liquidity_rating = "POOR"
        recommendation = "PROCEED_WITH_CAUTION"
        slippage_risk = "HIGH"
    else:
        liquidity_rating = "INADEQUATE"
        recommendation = "AVOID"
        slippage_risk = "HIGH"
    
    # Suggest maximum safe position size (< 2% of avg volume)
    suggested_max_size = avg_volume_usd * 0.02
    
    # Volume consistency (std dev)
    if len(volumes) > 1:
        mean_vol = sum(volumes) / len(volumes)
        variance = sum((v - mean_vol) ** 2 for v in volumes) / len(volumes)
        std_dev = variance ** 0.5
        volume_consistency_pct = (std_dev / mean_vol * 100) if mean_vol > 0 else 0
    else:
        volume_consistency_pct = 0
    
    result = {
        "trading_pair": config.trading_pair,
        "avg_volume_usd": round(avg_volume_usd, 2),
        "position_size_usd": config.position_size_usd,
        "position_as_pct_volume": round(position_as_pct_volume, 3),
        "liquidity_rating": liquidity_rating,
        "recommendation": recommendation,
        "suggested_max_size": round(suggested_max_size, 2),
        "slippage_risk": slippage_risk,
        "volume_consistency_pct": round(volume_consistency_pct, 2),
        "sample_size": len(recent_candles),
    }
    
    summary = (
        f"Liquidity Check - {config.trading_pair}:\n"
        f"• Avg volume: ${avg_volume_usd:,.0f} / hour\n"
        f"• Position: ${config.position_size_usd:,.0f} ({position_as_pct_volume:.2f}% of avg volume)\n"
        f"• Rating: {liquidity_rating}\n"
        f"• Slippage risk: {slippage_risk}\n"
        f"• Recommendation: {recommendation}\n"
        f"• Suggested max: ${suggested_max_size:,.0f}\n"
    )
    
    logger.info(
        f"Liquidity {config.trading_pair}: "
        f"${config.position_size_usd} is {position_as_pct_volume:.2f}% of ${avg_volume_usd:,.0f} avg volume"
    )
    
    return RoutineResult(
        text=summary,
        table_data=[result],
        table_columns=list(result.keys()),
    )
