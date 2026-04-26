"""Validate trading setup quality and entry readiness.

Takes a candidate from high_vol_coin_levels and validates:
1. Price proximity to entry levels
2. Technical confirmation (RSI, ADX, volume)
3. Stop-loss feasibility
4. Overall setup quality score

Returns a GO/NO-GO decision with detailed reasoning.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field
from telegram.ext import ContextTypes

from config_manager import get_client
from routines.base import RoutineResult
from routines.tech_overlay import compute_technical_indicators, Config as TechConfig

logger = logging.getLogger(__name__)


class Config(BaseModel):
    """Configuration for setup validation."""

    # Required: candidate info from high_vol_coin_levels
    trading_pair: str = Field(..., description="Trading pair (e.g., 'BTC-USDT')")
    connector: str = Field(default="hyperliquid_perpetual", description="Perpetual connector")
    bias: str = Field(..., description="LONG or SHORT")
    last_price: float = Field(..., description="Current price")
    
    # Key levels from high_vol_coin_levels
    pullback_level: float = Field(..., description="Pullback/EMA entry")
    breakout_level: float = Field(..., description="Breakout resistance")
    breakdown_level: float = Field(..., description="Breakdown support")
    invalid_long_level: float = Field(..., description="Long invalidation")
    invalid_short_level: float = Field(..., description="Short invalidation")
    atr_pct: float = Field(..., description="ATR %")
    
    # Candle config
    interval: str = Field(default="5m", description="Candle interval")
    max_records: int = Field(default=72, description="Candles to fetch")
    
    # Thresholds
    proximity_pct: float = Field(default=1.5, description="Max % from level to consider 'near'")
    max_stop_pct: float = Field(default=4.5, description="Max acceptable stop % (for risk budget)")
    min_quality_score: float = Field(default=60, description="Min quality score to consider entry")
    
    # RSI thresholds
    rsi_oversold: float = Field(default=40, description="RSI oversold for LONG")
    rsi_overbought: float = Field(default=60, description="RSI overbought for SHORT")
    
    # ADX threshold
    min_adx: float = Field(default=20, description="Min ADX for trend strength")


def _distance_pct(price: float, level: float) -> float:
    """Calculate % distance between price and level."""
    if price == 0:
        return 999.0
    return abs((level - price) / price) * 100


def _validate_setup(config: Config, tech: Any) -> dict[str, Any]:
    """Core setup validation logic."""
    
    # 1. Determine nearest entry level based on bias
    if config.bias == "LONG":
        # For LONG: prefer pullback to EMA, or breakout above resistance
        dist_pullback = _distance_pct(config.last_price, config.pullback_level)
        dist_breakout = _distance_pct(config.last_price, config.breakout_level)
        
        if dist_pullback < dist_breakout:
            nearest_level = config.pullback_level
            level_type = "pullback"
            dist_to_entry = dist_pullback
        else:
            nearest_level = config.breakout_level
            level_type = "breakout"
            dist_to_entry = dist_breakout
        
        # Stop would be below invalidation
        stop_level = config.invalid_long_level - (config.last_price * config.atr_pct * 0.15 / 100)
        required_stop_pct = _distance_pct(config.last_price, stop_level)
        
    elif config.bias == "SHORT":
        # For SHORT: prefer pullback to EMA, or breakdown below support
        dist_pullback = _distance_pct(config.last_price, config.pullback_level)
        dist_breakdown = _distance_pct(config.last_price, config.breakdown_level)
        
        if dist_pullback < dist_breakdown:
            nearest_level = config.pullback_level
            level_type = "pullback"
            dist_to_entry = dist_pullback
        else:
            nearest_level = config.breakdown_level
            level_type = "breakdown"
            dist_to_entry = dist_breakdown
        
        # Stop would be above invalidation
        stop_level = config.invalid_short_level + (config.last_price * config.atr_pct * 0.15 / 100)
        required_stop_pct = _distance_pct(config.last_price, stop_level)
        
    else:
        return {
            "ready": False,
            "decision": "SKIP",
            "reason": "NEUTRAL bias not supported",
            "quality_score": 0,
        }
    
    # 2. Check proximity to level
    is_near_level = dist_to_entry <= config.proximity_pct
    
    # 3. Check stop feasibility
    stop_acceptable = required_stop_pct <= config.max_stop_pct
    
    # 4. Technical confirmation
    rsi = tech.rsi_4h
    adx = tech.adx
    trend = tech.trend_direction
    bb_pos = tech.bollinger_position
    
    # RSI alignment
    if config.bias == "LONG":
        rsi_favorable = rsi < config.rsi_overbought
        rsi_strong = rsi < config.rsi_oversold
    else:  # SHORT
        rsi_favorable = rsi > config.rsi_oversold
        rsi_strong = rsi > config.rsi_overbought
    
    # Trend alignment
    trend_aligned = (
        (config.bias == "LONG" and trend == "bullish") or
        (config.bias == "SHORT" and trend == "bearish")
    )
    
    # ADX strength
    strong_trend = adx >= config.min_adx
    
    # 5. Calculate quality score (0-100)
    score = 0.0
    
    # Proximity (0-35 points)
    if dist_to_entry <= 0.5:
        score += 35  # Right at level
    elif dist_to_entry <= 1.0:
        score += 25  # Very close
    elif dist_to_entry <= 1.5:
        score += 15  # Near
    else:
        score += 5  # Too far
    
    # RSI (0-25 points)
    if rsi_strong:
        score += 25  # Strong oversold/overbought signal
    elif rsi_favorable:
        score += 15  # Favorable but not extreme
    else:
        score += 5  # Unfavorable
    
    # Trend (0-20 points)
    if trend_aligned and strong_trend:
        score += 20  # Perfect alignment
    elif trend_aligned:
        score += 12  # Aligned but weak
    elif strong_trend:
        score += 8  # Strong but misaligned
    else:
        score += 3  # Neither aligned nor strong
    
    # Stop distance (0-15 points)
    if required_stop_pct <= 2.5:
        score += 15  # Very tight
    elif required_stop_pct <= 3.5:
        score += 12  # Good
    elif required_stop_pct <= 4.5:
        score += 8  # Acceptable
    else:
        score += 3  # Wide
    
    # Bollinger position (0-5 points)
    if config.bias == "LONG" and bb_pos < -0.5:
        score += 5  # Near lower band for long
    elif config.bias == "SHORT" and bb_pos > 0.5:
        score += 5  # Near upper band for short
    elif abs(bb_pos) < 0.3:
        score += 3  # Near middle
    else:
        score += 1
    
    # 6. Decision logic
    if not stop_acceptable:
        decision = "SKIP"
        reason = f"Stop too wide: {required_stop_pct:.2f}% > {config.max_stop_pct}% limit"
        ready = False
        
    elif score >= config.min_quality_score and is_near_level:
        decision = "GO"
        reason = f"High-quality {config.bias} setup at {level_type} level"
        ready = True
        
    elif score >= config.min_quality_score:
        decision = "WAIT"
        reason = f"Good quality but wait for {level_type} @ {nearest_level:.4f} ({dist_to_entry:.2f}% away)"
        ready = False
        
    elif is_near_level:
        decision = "MARGINAL"
        reason = f"Near {level_type} but weak confirmation (score={score:.0f}, RSI={rsi:.0f}, ADX={adx:.0f})"
        ready = False
        
    else:
        decision = "SKIP"
        reason = f"Too far from levels ({dist_to_entry:.2f}%) with weak technicals (score={score:.0f})"
        ready = False
    
    return {
        "ready": ready,
        "decision": decision,
        "reason": reason,
        "quality_score": round(score, 1),
        
        # Level info
        "nearest_level": round(nearest_level, 6),
        "level_type": level_type,
        "distance_to_entry_pct": round(dist_to_entry, 2),
        "is_near_level": is_near_level,
        
        # Technical indicators
        "rsi": round(rsi, 1),
        "rsi_favorable": rsi_favorable,
        "rsi_strong": rsi_strong,
        "adx": round(adx, 1),
        "trend_direction": trend,
        "trend_aligned": trend_aligned,
        "strong_trend": strong_trend,
        "bollinger_position": round(bb_pos, 2),
        
        # Risk metrics
        "required_stop_pct": round(required_stop_pct, 2),
        "stop_acceptable": stop_acceptable,
        "stop_level": round(stop_level, 6),
    }


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    """Validate trading setup and return GO/NO-GO decision."""
    
    client = await get_client(context._chat_id, context=context)
    if not client:
        return "No server available"
    
    # Fetch candles
    try:
        result = await client.market_data.get_candles(
            connector_name=config.connector,
            trading_pair=config.trading_pair,
            interval=config.interval,
            max_records=config.max_records,
        )
        
        if isinstance(result, list):
            candles = result
        elif isinstance(result, dict):
            candles = result.get("data", [])
        else:
            return f"Invalid candle data for {config.trading_pair}"
            
    except Exception as e:
        logger.error("Failed to fetch candles: %s", e)
        return f"Candle fetch failed: {e}"
    
    if not candles or len(candles) < 50:
        return f"Insufficient candle data ({len(candles) if candles else 0} candles)"
    
    # Compute technical indicators
    tech = compute_technical_indicators(candles, TechConfig())
    if not tech:
        return "Failed to compute technical indicators"
    
    # Validate setup
    validation = _validate_setup(config, tech)
    
    # Format output
    decision_emoji = {
        "GO": "✅",
        "WAIT": "⏳",
        "MARGINAL": "⚠️",
        "SKIP": "❌",
    }.get(validation["decision"], "❓")
    
    lines = [
        f"{decision_emoji} **{validation['decision']}**: {config.trading_pair} ({config.bias})",
        f"",
        f"**Quality Score:** {validation['quality_score']}/100",
        f"**Reason:** {validation['reason']}",
        f"",
        f"📍 **Levels:**",
        f"  • Price: ${config.last_price:.4f}",
        f"  • {validation['level_type'].title()}: ${validation['nearest_level']:.4f} ({validation['distance_to_entry_pct']}% away)",
        f"  • Stop: ${validation['stop_level']:.4f} ({validation['required_stop_pct']}%)",
        f"",
        f"📊 **Technicals:**",
        f"  • RSI: {validation['rsi']} {'✓ favorable' if validation['rsi_favorable'] else '✗ unfavorable'} {'(STRONG)' if validation['rsi_strong'] else ''}",
        f"  • ADX: {validation['adx']} {'✓ trending' if validation['strong_trend'] else '✗ weak'}",
        f"  • Trend: {validation['trend_direction']} {'✓ aligned' if validation['trend_aligned'] else '✗ misaligned'}",
        f"  • Bollinger: {validation['bollinger_position']:.2f}",
    ]
    
    text = "\n".join(lines)
    
    return RoutineResult(
        text=text,
        table_data=[validation],
        sections=[
            {
                "title": "validation",
                "content": text,
            }
        ],
    )
