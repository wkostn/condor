"""Technical Overlay Routine - Add technical analysis to market scans.

This routine computes technical indicators for any asset and populates the
TechnicalIndicators structure in MarketState objects.

Based on: The Agentic Trading Platform Technical Reference v4.0, Section 4.4

Indicators Computed:
- RSI (4H, 1D): Momentum oscillator (0-100)
- ADX: Trend strength indicator (0-100, >25 = trending)
- Bollinger Bands: Volatility position (-1 to +1)
- ATR: Average True Range as % of price
- EMA: 20, 50, 200 period moving averages
- Support/Resistance: Pivot-based levels

Usage:
    Can be called standalone or integrated into morning_scan routine.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any, List, Optional

import numpy as np
from pydantic import BaseModel, Field

from schemas.market_state import TechnicalIndicators

logger = logging.getLogger(__name__)


class Config(BaseModel):
    """Configuration for tech_overlay routine."""
    
    rsi_period: int = Field(default=14, description="RSI calculation period")
    adx_period: int = Field(default=14, description="ADX calculation period")
    bb_period: int = Field(default=20, description="Bollinger Bands period")
    bb_std_dev: float = Field(default=2.0, description="Bollinger Bands standard deviations")
    atr_period: int = Field(default=14, description="ATR calculation period")
    ema_periods: list[int] = Field(default=[20, 50, 200], description="EMA periods to compute")
    min_candles: int = Field(default=72, description="Minimum candles required for analysis")


def _ema(values: list[float], period: int) -> float:
    """Calculate Exponential Moving Average."""
    if not values or len(values) < period:
        return 0.0
    
    alpha = 2 / (period + 1)
    ema_value = values[0]
    
    for value in values[1:]:
        ema_value = value * alpha + ema_value * (1 - alpha)
    
    return ema_value


def _ema_series(values: list[float], period: int) -> list[float]:
    """Calculate EMA series (all values, not just last)."""
    if not values or len(values) < period:
        return []
    
    alpha = 2 / (period + 1)
    ema_series = [values[0]]
    
    for value in values[1:]:
        ema_series.append(value * alpha + ema_series[-1] * (1 - alpha))
    
    return ema_series


def _rsi(closes: list[float], period: int = 14) -> float:
    """Calculate Relative Strength Index (RSI).
    
    Returns value between 0-100:
    - < 30: Oversold
    - > 70: Overbought
    - 50: Neutral
    """
    if len(closes) < period + 1:
        return 50.0  # Neutral default
    
    # Calculate price changes
    changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    
    # Separate gains and losses
    gains = [max(change, 0) for change in changes]
    losses = [abs(min(change, 0)) for change in changes]
    
    # Calculate average gain/loss
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def _true_range(high: float, low: float, prev_close: float) -> float:
    """Calculate True Range for a single bar."""
    return max(
        high - low,
        abs(high - prev_close),
        abs(low - prev_close)
    )


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    """Calculate Average True Range (ATR)."""
    if len(closes) < period + 1:
        return 0.0
    
    true_ranges = [
        _true_range(highs[i], lows[i], closes[i-1])
        for i in range(1, len(closes))
    ]
    
    atr_value = sum(true_ranges[-period:]) / period
    return atr_value


def _atr_percent(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    """Calculate ATR as percentage of current price."""
    if not closes or closes[-1] == 0:
        return 0.0
    
    atr_value = _atr(highs, lows, closes, period)
    return (atr_value / closes[-1]) * 100


def _dm(highs: list[float], lows: list[float]) -> tuple[list[float], list[float]]:
    """Calculate Directional Movement (+DM, -DM)."""
    plus_dm = []
    minus_dm = []
    
    for i in range(1, len(highs)):
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        
        if up_move > down_move and up_move > 0:
            plus_dm.append(up_move)
            minus_dm.append(0)
        elif down_move > up_move and down_move > 0:
            plus_dm.append(0)
            minus_dm.append(down_move)
        else:
            plus_dm.append(0)
            minus_dm.append(0)
    
    return plus_dm, minus_dm


def _adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    """Calculate Average Directional Index (ADX).
    
    Returns value between 0-100:
    - < 20: Weak trend (ranging)
    - 20-25: Developing trend
    - 25-50: Strong trend
    - > 50: Very strong trend
    """
    if len(closes) < period * 2:
        return 0.0
    
    # Calculate True Range
    tr_list = [
        _true_range(highs[i], lows[i], closes[i-1])
        for i in range(1, len(closes))
    ]
    
    # Calculate Directional Movement
    plus_dm, minus_dm = _dm(highs, lows)
    
    # Smooth with period
    atr_smooth = sum(tr_list[-period:]) / period
    plus_di_smooth = sum(plus_dm[-period:]) / period
    minus_di_smooth = sum(minus_dm[-period:]) / period
    
    if atr_smooth == 0:
        return 0.0
    
    # Calculate DI
    plus_di = 100 * (plus_di_smooth / atr_smooth)
    minus_di = 100 * (minus_di_smooth / atr_smooth)
    
    # Calculate DX
    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 0.0
    
    dx = 100 * abs(plus_di - minus_di) / di_sum
    
    # ADX is EMA of DX (simplified here as average)
    return dx


def _bollinger_bands(closes: list[float], period: int = 20, std_dev: float = 2.0) -> tuple[float, float, float]:
    """Calculate Bollinger Bands (upper, middle, lower)."""
    if len(closes) < period:
        return 0.0, 0.0, 0.0
    
    recent = closes[-period:]
    middle = sum(recent) / period
    std = statistics.stdev(recent) if len(recent) > 1 else 0
    
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    
    return upper, middle, lower


def _bollinger_position(price: float, upper: float, middle: float, lower: float) -> float:
    """Calculate position within Bollinger Bands.
    
    Returns value between -1 and +1:
    - -1: At or below lower band
    - 0: At middle band
    - +1: At or above upper band
    """
    if upper == lower:
        return 0.0
    
    band_width = upper - lower
    position_in_band = (price - middle) / (band_width / 2)
    
    # Clamp to [-1, 1]
    return max(-1.0, min(1.0, position_in_band))


def _find_pivot_levels(highs: list[float], lows: list[float], closes: list[float], num_levels: int = 3) -> tuple[list[float], list[float]]:
    """Find support and resistance levels using pivot points.
    
    Returns:
        (support_levels, resistance_levels) - each is a list of floats
    """
    if len(closes) < 10:
        return [], []
    
    # Use last 50 bars for pivot calculation
    window = min(50, len(closes))
    recent_highs = highs[-window:]
    recent_lows = lows[-window:]
    recent_closes = closes[-window:]
    
    # Calculate pivot point
    high = max(recent_highs)
    low = min(recent_lows)
    close = recent_closes[-1]
    
    pivot = (high + low + close) / 3
    
    # Calculate support and resistance levels
    r1 = 2 * pivot - low
    r2 = pivot + (high - low)
    r3 = high + 2 * (pivot - low)
    
    s1 = 2 * pivot - high
    s2 = pivot - (high - low)
    s3 = low - 2 * (high - pivot)
    
    # Filter and sort
    current_price = closes[-1]
    
    resistances = [r for r in [r1, r2, r3] if r > current_price]
    supports = [s for s in [s1, s2, s3] if s < current_price]
    
    resistances.sort()
    supports.sort(reverse=True)
    
    return supports[:num_levels], resistances[:num_levels]


def _determine_trend_direction(
    price: float,
    ema_20: float,
    ema_50: float,
    adx: float,
    rsi: float
) -> str:
    """Determine overall trend direction.
    
    Returns: "bullish" | "bearish" | "neutral"
    """
    # Weak trend = neutral
    if adx < 20:
        return "neutral"
    
    # EMA alignment
    if ema_20 > ema_50 and price > ema_20:
        if rsi > 45:  # Not oversold
            return "bullish"
    elif ema_20 < ema_50 and price < ema_20:
        if rsi < 55:  # Not overbought
            return "bearish"
    
    return "neutral"


def compute_technical_indicators(
    candles: list[dict[str, Any]],
    config: Optional[Config] = None
) -> Optional[TechnicalIndicators]:
    """Compute all technical indicators for a set of candles.
    
    Args:
        candles: List of OHLCV candles (dicts with 'open', 'high', 'low', 'close', 'volume')
        config: Optional configuration (uses defaults if None)
    
    Returns:
        TechnicalIndicators object or None if insufficient data
    """
    if config is None:
        config = Config()
    
    if len(candles) < config.min_candles:
        logger.debug(f"Insufficient candles: {len(candles)} < {config.min_candles}")
        return None
    
    try:
        # Extract price arrays
        closes = [float(c['close']) for c in candles]
        highs = [float(c['high']) for c in candles]
        lows = [float(c['low']) for c in candles]
        
        if not closes or closes[-1] == 0:
            return None
        
        current_price = closes[-1]
        
        # Calculate momentum indicators
        rsi_4h = _rsi(closes, config.rsi_period)
        
        # For 1D RSI, we'd need daily candles. For now, use longer period on same timeframe
        rsi_1d = _rsi(closes, config.rsi_period * 6) if len(closes) >= config.rsi_period * 6 else rsi_4h
        
        # Calculate trend indicators
        adx_value = _adx(highs, lows, closes, config.adx_period)
        
        # Calculate EMAs
        ema_20 = _ema(closes, 20) if len(closes) >= 20 else current_price
        ema_50 = _ema(closes, 50) if len(closes) >= 50 else current_price
        ema_200 = _ema(closes, 200) if len(closes) >= 200 else current_price
        
        # Determine trend direction
        trend_direction = _determine_trend_direction(
            current_price, ema_20, ema_50, adx_value, rsi_4h
        )
        
        # Calculate Bollinger Bands
        upper, middle, lower = _bollinger_bands(closes, config.bb_period, config.bb_std_dev)
        bb_position = _bollinger_position(current_price, upper, middle, lower)
        
        # Calculate volatility
        atr_pct = _atr_percent(highs, lows, closes, config.atr_period)
        
        # Find support/resistance levels
        supports, resistances = _find_pivot_levels(highs, lows, closes, num_levels=3)
        
        return TechnicalIndicators(
            rsi_4h=round(rsi_4h, 2),
            rsi_1d=round(rsi_1d, 2),
            adx=round(adx_value, 2),
            trend_direction=trend_direction,
            bollinger_position=round(bb_position, 3),
            atr_percent=round(atr_pct, 3),
            support_levels=[round(s, 6) for s in supports],
            resistance_levels=[round(r, 6) for r in resistances],
            ema_20=round(ema_20, 6) if ema_20 > 0 else None,
            ema_50=round(ema_50, 6) if ema_50 > 0 else None,
            ema_200=round(ema_200, 6) if ema_200 > 0 else None,
        )
        
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        logger.error(f"Failed to compute technical indicators: {exc}")
        return None


def compute(candles: list[dict[str, Any]], config: Optional[Config] = None) -> Optional[TechnicalIndicators]:
    """Main entry point for the routine.
    
    This is a utility routine that can be called by other routines (like morning_scan)
    or standalone for testing. Not meant to be run directly from the web UI.
    
    Args:
        candles: List of OHLCV candle dictionaries
        config: Optional configuration for indicator periods
        
    Returns:
        TechnicalIndicators object or None if computation fails
    """
    return compute_technical_indicators(candles, config)
