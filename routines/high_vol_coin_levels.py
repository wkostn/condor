"""Rank liquid high-volatility perpetual coins and surface logical trade levels."""

from __future__ import annotations

import asyncio
import logging
import math
import statistics
from typing import Any

import aiohttp
from pydantic import BaseModel, Field, field_validator
from telegram.ext import ContextTypes

from config_manager import get_client
from routines.base import RoutineResult

logger = logging.getLogger(__name__)

BINANCE_FUTURES_TICKER = "https://fapi.binance.com/fapi/v1/ticker/24hr"
MAX_CONCURRENT = 8


class Config(BaseModel):
    """Find liquid high-volatility perp candidates with directional bias and levels."""

    connector: str = Field(default="binance_perpetual", description="Perpetual connector to use for candles")
    top_n: int = Field(default=20, description="Top markets by external 24h quote volume to inspect")
    candidates: int = Field(default=5, description="How many ranked candidates to return")
    interval: str = Field(default="5m", description="Candle interval for analysis")
    max_records: int = Field(default=72, description="How many candles to fetch per market")
    breakout_window: int = Field(default=12, description="Recent candles used for breakout and breakdown levels")
    min_volume_usd: float = Field(default=25_000_000, description="Minimum 24h quote volume in USD")
    exclude_pairs: list[str] = Field(default_factory=list, description="Pairs to skip")

    @field_validator("exclude_pairs", mode="before")
    @classmethod
    def normalize_exclude_pairs(cls, v):
        """Convert None to empty list for compatibility."""
        return v if v is not None else []


async def _fetch_top_pairs(top_n: int, min_volume_usd: float, exclude_pairs: set[str]) -> list[dict[str, Any]]:
    async with aiohttp.ClientSession() as session:
        async with session.get(BINANCE_FUTURES_TICKER) as resp:
            resp.raise_for_status()
            payload = await resp.json()

    pairs: list[dict[str, Any]] = []
    for item in payload:
        symbol = str(item.get("symbol", ""))
        if not symbol.endswith("USDT"):
            continue
        base = symbol[:-4]
        trading_pair = f"{base}-USDT"
        if trading_pair in exclude_pairs:
            continue

        quote_volume = float(item.get("quoteVolume", 0) or 0)
        if quote_volume < min_volume_usd:
            continue

        pairs.append(
            {
                "symbol": symbol,
                "trading_pair": trading_pair,
                "quote_volume": quote_volume,
                "last_price": float(item.get("lastPrice", 0) or 0),
                "change_24h_pct": float(item.get("priceChangePercent", 0) or 0),
            }
        )

    pairs.sort(key=lambda row: row["quote_volume"], reverse=True)
    return pairs[:top_n]


async def _fetch_candles(
    client: Any,
    connector: str,
    trading_pair: str,
    interval: str,
    max_records: int,
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]] | None:
    async with semaphore:
        try:
            result = await client.market_data.get_candles(
                connector_name=connector,
                trading_pair=trading_pair,
                interval=interval,
                max_records=max_records,
            )
        except Exception as exc:
            logger.debug("Candle fetch failed for %s: %s", trading_pair, exc)
            return None

    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        data = result.get("data")
        return data if isinstance(data, list) else None
    return None


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    alpha = 2 / (period + 1)
    ema_value = values[0]
    for value in values[1:]:
        ema_value = value * alpha + ema_value * (1 - alpha)
    return ema_value


def _atr_pct(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 0.0
    true_ranges: list[float] = []
    for idx in range(1, len(closes)):
        true_ranges.append(
            max(
                highs[idx] - lows[idx],
                abs(highs[idx] - closes[idx - 1]),
                abs(lows[idx] - closes[idx - 1]),
            )
        )
    atr = sum(true_ranges[-period:]) / period
    last_close = closes[-1]
    if last_close <= 0:
        return 0.0
    return (atr / last_close) * 100


def _pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return ((current - previous) / previous) * 100


def _analyze_pair(pair: dict[str, Any], candles: list[dict[str, Any]], breakout_window: int) -> dict[str, Any] | None:
    if len(candles) < max(55, breakout_window + 2):
        return None

    try:
        closes = [float(row["close"]) for row in candles]
        highs = [float(row["high"]) for row in candles]
        lows = [float(row["low"]) for row in candles]
        volumes = [float(row.get("volume", 0) or 0) for row in candles]
    except (KeyError, TypeError, ValueError):
        return None

    if not closes or closes[-1] <= 0:
        return None

    last_price = closes[-1]
    ema_fast = _ema(closes[-20:], 20)
    ema_slow = _ema(closes[-50:], 50)
    atr_pct = _atr_pct(highs, lows, closes)
    if atr_pct <= 0:
        return None

    one_hour_high = max(highs[-breakout_window:])
    one_hour_low = min(lows[-breakout_window:])
    four_hour_high = max(highs[-48:]) if len(highs) >= 48 else max(highs)
    four_hour_low = min(lows[-48:]) if len(lows) >= 48 else min(lows)
    one_hour_range_pct = _pct_change(one_hour_high, one_hour_low)
    momentum_pct = _pct_change(last_price, closes[-breakout_window - 1])

    returns: list[float] = []
    for idx in range(1, len(closes)):
        prev = closes[idx - 1]
        if prev > 0:
            returns.append((closes[idx] - prev) / prev)
    realized_vol_pct = statistics.pstdev(returns[-24:]) * math.sqrt(max(len(returns[-24:]), 1)) * 100 if returns else 0.0

    volume_tail = volumes[-24:] if len(volumes) >= 24 else volumes
    volume_factor = sum(volume_tail) / len(volume_tail) if volume_tail else 0.0
    if volume_factor <= 0:
        return None

    if ema_fast > ema_slow and last_price >= ema_fast and momentum_pct > 0:
        bias = "LONG"
    elif ema_fast < ema_slow and last_price <= ema_fast and momentum_pct < 0:
        bias = "SHORT"
    else:
        bias = "NEUTRAL"

    score = (
        atr_pct * 2.2
        + abs(momentum_pct) * 0.8
        + realized_vol_pct * 0.7
        + min(pair["quote_volume"] / 100_000_000, 5.0)
    )

    levels = {
        "pullback_level": round(ema_fast, 6),
        "breakout_level": round(one_hour_high, 6),
        "breakdown_level": round(one_hour_low, 6),
        "invalid_long_level": round(min(one_hour_low, four_hour_low), 6),
        "invalid_short_level": round(max(one_hour_high, four_hour_high), 6),
    }

    return {
        "trading_pair": pair["trading_pair"],
        "bias": bias,
        "score": round(score, 3),
        "last_price": round(last_price, 6),
        "change_24h_pct": round(pair["change_24h_pct"], 2),
        "quote_volume_usd": round(pair["quote_volume"], 2),
        "atr_pct": round(atr_pct, 3),
        "realized_vol_pct": round(realized_vol_pct, 3),
        "momentum_pct": round(momentum_pct, 3),
        "one_hour_range_pct": round(one_hour_range_pct, 3),
        "four_hour_high": round(four_hour_high, 6),
        "four_hour_low": round(four_hour_low, 6),
        **levels,
    }


def _format_rows(rows: list[dict[str, Any]]) -> str:
    lines = ["High-volatility perp candidates:"]
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index}. {row['trading_pair']} | {row['bias']} | score {row['score']:.2f} | "
            f"last {row['last_price']:.4f} | ATR {row['atr_pct']:.2f}% | "
            f"pullback {row['pullback_level']:.4f} | breakout {row['breakout_level']:.4f} | "
            f"breakdown {row['breakdown_level']:.4f}"
        )
    return "\n".join(lines)


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    client = await get_client(context._chat_id, context=context)
    if not client:
        return "No server available"

    exclude_pairs = {pair.upper() for pair in config.exclude_pairs}
    top_pairs = await _fetch_top_pairs(config.top_n, config.min_volume_usd, exclude_pairs)
    if not top_pairs:
        return "No liquid high-volatility candidates found"

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    candle_tasks = [
        _fetch_candles(
            client=client,
            connector=config.connector,
            trading_pair=pair["trading_pair"],
            interval=config.interval,
            max_records=config.max_records,
            semaphore=semaphore,
        )
        for pair in top_pairs
    ]
    candle_results = await asyncio.gather(*candle_tasks)

    analyzed: list[dict[str, Any]] = []
    for pair, candles in zip(top_pairs, candle_results):
        if not candles:
            continue
        result = _analyze_pair(pair, candles, config.breakout_window)
        if result and result["bias"] != "NEUTRAL":
            analyzed.append(result)

    if not analyzed:
        return "No directional high-volatility candidates found"

    analyzed.sort(key=lambda row: row["score"], reverse=True)
    rows = analyzed[: config.candidates]
    text = _format_rows(rows)

    return RoutineResult(
        text=text,
        table_data=rows,
        table_columns=[
            "trading_pair",
            "bias",
            "score",
            "last_price",
            "atr_pct",
            "momentum_pct",
            "pullback_level",
            "breakout_level",
            "breakdown_level",
            "invalid_long_level",
            "invalid_short_level",
        ],
        sections=[
            {
                "title": "summary",
                "content": text,
            }
        ],
    )
