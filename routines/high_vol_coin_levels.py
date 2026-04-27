"""Rank liquid high-volatility perpetual coins and surface logical trade levels.

Architecture: Hyperliquid-first with tiered caching.

Data flow:
    1. REAL-TIME  (~700ms) - Single Hyperliquid `metaAndAssetCtxs` call
       → All 230 perps: price, 24h volume, funding, open interest, mark price
    2. CACHED 7 DAYS       - Curated category map (meme, defi, layer1, etc.)
       → Enriches metadata without API calls on each run
    3. REAL-TIME  (~250ms/pair, 8 parallel) - Hyperliquid candle snapshots
       → Only for top_n filtered candidates, direct from exchange API
    4. ANALYSIS   (in-process) - EMA, ATR, bias, levels, scoring
       → Pure computation, no I/O

Typical wall-clock: 1.5–3s for 5 candidates.
"""

from __future__ import annotations

import asyncio
import logging
import math
import statistics
import time
from typing import Any

import aiohttp
from pydantic import BaseModel, Field, field_validator
from telegram.ext import ContextTypes

from config_manager import get_client
from routines.base import RoutineResult
from utils.shared_cache import get_cached, set_cached

logger = logging.getLogger(__name__)

HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
MAX_CONCURRENT = 8

# ── Cache keys & TTLs ────────────────────────────────────────────────
CACHE_KEY_CATEGORIES = "hl_categories_v2"
CACHE_TTL_CATEGORIES_MIN = 10080  # 7 days — categories rarely change


# ── Category mapping ─────────────────────────────────────────────────

# Curated mapping for the top Hyperliquid perps.
# This is faster and more accurate than CoinGecko for the ~230 perps that matter.
# Unknown coins default to "other".
_CATEGORY_MAP: dict[str, str] = {
    # Layer 1
    "BTC": "layer1", "ETH": "layer1", "SOL": "layer1", "ADA": "layer1",
    "AVAX": "layer1", "DOT": "layer1", "ATOM": "layer1", "NEAR": "layer1",
    "SUI": "layer1", "APT": "layer1", "SEI": "layer1", "ICP": "layer1",
    "FTM": "layer1", "HBAR": "layer1", "ALGO": "layer1", "XLM": "layer1",
    "XRP": "layer1", "TRX": "layer1", "TON": "layer1", "EOS": "layer1",
    "FIL": "layer1", "EGLD": "layer1", "KAVA": "layer1", "INJ": "layer1",
    "TIA": "layer1", "KAS": "layer1", "BERA": "layer1", "S": "layer1",
    "MOVE": "layer1",
    # Layer 2
    "MATIC": "layer2", "ARB": "layer2", "OP": "layer2", "STRK": "layer2",
    "MNT": "layer2", "MANTA": "layer2", "BLAST": "layer2", "ZK": "layer2",
    "METIS": "layer2", "IMX": "layer2", "ZETA": "layer2",
    # Meme
    "DOGE": "meme", "SHIB": "meme", "PEPE": "meme", "WIF": "meme",
    "FLOKI": "meme", "BONK": "meme", "MEME": "meme", "NEIRO": "meme",
    "POPCAT": "meme", "MOG": "meme", "BRETT": "meme", "MYRO": "meme",
    "PNUT": "meme", "ACT": "meme", "GOAT": "meme", "FARTCOIN": "meme",
    "TRUMP": "meme", "PENGU": "meme", "SPX": "meme", "TURBO": "meme",
    "BABYDOGE": "meme", "LADYS": "meme", "BOME": "meme",
    "HYPE": "meme",
    # DeFi
    "UNI": "defi", "AAVE": "defi", "LINK": "defi", "MKR": "defi",
    "SNX": "defi", "CRV": "defi", "COMP": "defi", "SUSHI": "defi",
    "LDO": "defi", "PENDLE": "defi", "DYDX": "defi", "GMX": "defi",
    "JUP": "defi", "RAY": "defi", "ORCA": "defi", "RDNT": "defi",
    "JTO": "defi", "ENA": "defi", "ETHFI": "defi", "EIGEN": "defi",
    "ONDO": "defi", "PYTH": "defi",
    # AI
    "FET": "ai", "RENDER": "ai", "TAO": "ai", "RNDR": "ai",
    "OCEAN": "ai", "AGIX": "ai", "WLD": "ai", "AR": "ai",
    "AKT": "ai", "ARKM": "ai", "VIRTUAL": "ai", "AI16Z": "ai",
    "GRIFFAIN": "ai", "AIXBT": "ai", "ZEREBRO": "ai",
    # Gaming / Metaverse
    "AXS": "gaming", "SAND": "gaming", "MANA": "gaming", "GALA": "gaming",
    "ENJ": "gaming", "ILV": "gaming", "PIXEL": "gaming", "PORTAL": "gaming",
    "RON": "gaming", "PRIME": "gaming", "BEAM": "gaming",
    # Infrastructure / Utility
    "BNB": "infra", "RUNE": "infra", "STX": "infra", "GRT": "infra",
    "QNT": "infra", "VET": "infra", "IOTA": "infra",
    # TradFi
    "TSLA": "tradfi",
}


def _get_category(base_asset: str) -> str:
    """Look up category from curated map. Defaults to 'other'."""
    return _CATEGORY_MAP.get(base_asset.upper(), "other")


# ── Hyperliquid API ──────────────────────────────────────────────────

async def _fetch_meta_and_contexts() -> tuple[list[dict], list[dict]]:
    """Single call to get ALL Hyperliquid perps with live market data.

    Returns (universe, asset_contexts) where each asset_context has:
        dayNtlVlm, funding, openInterest, markPx, midPx, prevDayPx, etc.
    """
    async with aiohttp.ClientSession() as session:
        async with session.post(
            HYPERLIQUID_INFO_URL, json={"type": "metaAndAssetCtxs"}
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

    return data[0].get("universe", []), data[1]


async def _fetch_candles_direct(
    coin: str,
    interval: str,
    lookback_hours: float,
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]] | None:
    """Fetch candles directly from Hyperliquid public API (no hummingbot)."""
    now_ms = int(time.time() * 1000)
    start_ms = int((time.time() - lookback_hours * 3600) * 1000)

    async with semaphore:
        try:
            async with session.post(
                HYPERLIQUID_INFO_URL,
                json={
                    "type": "candleSnapshot",
                    "req": {
                        "coin": coin,
                        "interval": interval,
                        "startTime": start_ms,
                        "endTime": now_ms,
                    },
                },
            ) as resp:
                if resp.status != 200:
                    logger.warning("Candle fetch %s: HTTP %s", coin, resp.status)
                    return None
                raw = await resp.json()
        except Exception as exc:
            logger.warning("Candle fetch %s failed: %s", coin, exc)
            return None

    if not raw or not isinstance(raw, list):
        return None

    # Convert Hyperliquid format {t,T,s,i,o,c,h,l,v,n} → standard
    candles = []
    for r in raw:
        try:
            candles.append({
                "open": float(r["o"]),
                "close": float(r["c"]),
                "high": float(r["h"]),
                "low": float(r["l"]),
                "volume": float(r["v"]),
                "timestamp": r["t"],
            })
        except (KeyError, TypeError, ValueError):
            continue
    return candles


# ── Technical analysis (pure computation) ────────────────────────────

def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    alpha = 2 / (period + 1)
    ema_value = values[0]
    for value in values[1:]:
        ema_value = value * alpha + ema_value * (1 - alpha)
    return ema_value


def _atr_pct(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> float:
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


def _price_decimals(price: float) -> int:
    """Determine appropriate decimal places based on price magnitude.

    Ensures at least 4 significant digits for price levels so that
    sub-cent coins (PENGU $0.009) aren't rounded to meaningless values.
    """
    if price <= 0:
        return 8
    if price >= 1000:   # BTC, ETH at high prices
        return 2
    if price >= 1:      # SOL, AVAX, LINK
        return 4
    if price >= 0.01:   # SHIB-like mid-range
        return 6
    return 8            # ultra-low-price coins


def _round_price(value: float, ref_price: float) -> float:
    """Round a price/level value using adaptive precision based on reference price."""
    return round(value, _price_decimals(ref_price))


def _fmt_price(value: float) -> str:
    """Format a price for text output with adaptive decimals."""
    decimals = _price_decimals(value)
    return f"{value:.{decimals}f}"


def _analyze_pair(
    pair: dict[str, Any], candles: list[dict[str, Any]], breakout_window: int
) -> dict[str, Any] | None:
    min_candles = max(55, breakout_window + 2)
    if len(candles) < min_candles:
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
    realized_vol_pct = (
        statistics.pstdev(returns[-24:])
        * math.sqrt(max(len(returns[-24:]), 1))
        * 100
        if returns
        else 0.0
    )

    volume_tail = volumes[-24:] if len(volumes) >= 24 else volumes
    volume_factor = sum(volume_tail) / len(volume_tail) if volume_tail else 0.0
    if volume_factor <= 0:
        return None

    # Directional bias
    if ema_fast > ema_slow and last_price >= ema_fast and momentum_pct > 0:
        bias = "LONG"
    elif ema_fast < ema_slow and last_price <= ema_fast and momentum_pct < 0:
        bias = "SHORT"
    else:
        bias = "NEUTRAL"

    # Composite score: volatility + momentum + volume
    score = (
        atr_pct * 2.2
        + abs(momentum_pct) * 0.8
        + realized_vol_pct * 0.7
        + min(pair["quote_volume"] / 100_000_000, 5.0)
    )

    rp = lambda v: _round_price(v, last_price)

    levels = {
        "pullback_level": rp(ema_fast),
        "breakout_level": rp(one_hour_high),
        "breakdown_level": rp(one_hour_low),
        "invalid_long_level": rp(min(one_hour_low, four_hour_low)),
        "invalid_short_level": rp(max(one_hour_high, four_hour_high)),
    }

    return {
        "trading_pair": pair["trading_pair"],
        "bias": bias,
        "score": round(score, 3),
        "last_price": rp(last_price),
        "change_24h_pct": round(pair.get("change_24h_pct", 0), 2),
        "quote_volume_usd": round(pair["quote_volume"], 2),
        "atr_pct": round(atr_pct, 3),
        "realized_vol_pct": round(realized_vol_pct, 3),
        "momentum_pct": round(momentum_pct, 3),
        "one_hour_range_pct": round(one_hour_range_pct, 3),
        "four_hour_high": rp(four_hour_high),
        "four_hour_low": rp(four_hour_low),
        "max_leverage": pair.get("max_leverage", 1),
        "category": pair.get("category", "other"),
        "funding_rate": pair.get("funding_rate", 0),
        "open_interest_usd": pair.get("open_interest_usd", 0),
        **levels,
    }


# ── Output formatting ────────────────────────────────────────────────

def _format_rows(rows: list[dict[str, Any]]) -> str:
    lines = ["High-volatility perp candidates:"]
    for i, r in enumerate(rows, start=1):
        fp = lambda v: _fmt_price(v)
        lines.append(
            f"{i}. {r['trading_pair']} | {r['bias']} | score {r['score']:.2f} | "
            f"last {fp(r['last_price'])} | ATR {r['atr_pct']:.2f}% | "
            f"24h chg {r['change_24h_pct']:+.2f}% | max_lev {r.get('max_leverage',1)}x | "
            f"vol ${r['quote_volume_usd']:,.0f} | "
            f"funding {r.get('funding_rate',0):.6f} | "
            f"cat {r.get('category','?')} | "
            f"pullback {fp(r['pullback_level'])} | breakout {fp(r['breakout_level'])} | "
            f"breakdown {fp(r['breakdown_level'])}"
        )
    return "\n".join(lines)


# ── Config ───────────────────────────────────────────────────────────

class Config(BaseModel):
    """Find liquid high-volatility perp candidates with directional bias and levels."""

    connector: str = Field(
        default="hyperliquid_perpetual",
        description="Perpetual connector (used for pair naming only)",
    )
    category: str = Field(
        default="all",
        description="Category filter: all, meme, ai, defi, gaming, layer1, layer2, infra, rwa, tradfi",
    )
    top_n: int = Field(
        default=30,
        description="Top markets by 24h volume to fetch candles for",
    )
    candidates: int = Field(
        default=5, description="How many ranked candidates to return"
    )
    interval: str = Field(default="5m", description="Candle interval for analysis")
    lookback_hours: float = Field(
        default=6.0,
        description="Hours of candle history to fetch (6h = ~72 5m candles)",
    )
    breakout_window: int = Field(
        default=12,
        description="Recent candles for breakout/breakdown levels",
    )
    min_volume_usd: float = Field(
        default=1_000_000, description="Minimum 24h notional volume in USD"
    )
    exclude_pairs: list[str] = Field(
        default_factory=list, description="Pairs to skip"
    )

    @field_validator("exclude_pairs", mode="before")
    @classmethod
    def normalize_exclude_pairs(cls, v):
        return v if v is not None else []


# ── Main entry point ─────────────────────────────────────────────────

async def run(
    config: Config, context: ContextTypes.DEFAULT_TYPE
) -> RoutineResult | str:
    """
    Hyperliquid-first scanner with tiered caching.

    Performance budget (typical):
        metaAndAssetCtxs  ~700ms  (1 call, all 230 perps)
        candle fetches    ~800ms  (top_n pairs, 8 parallel)
        analysis          ~10ms   (pure CPU)
        ─────────────────────────
        total             ~1.5s
    """
    t_start = time.monotonic()
    exclude_pairs = {p.upper() for p in config.exclude_pairs}

    # ── Step 1: Fetch ALL Hyperliquid perps + live market data ────────
    # Single API call → universe (meta) + asset contexts (price/vol/funding/OI)
    try:
        universe, asset_ctxs = await _fetch_meta_and_contexts()
    except Exception as exc:
        return f"Hyperliquid API error: {exc}"

    if not universe or len(universe) != len(asset_ctxs):
        return "Hyperliquid returned invalid data"

    t_meta = time.monotonic()

    # ── Step 2: Build enriched pair list ──────────────────────────────
    pairs: list[dict[str, Any]] = []
    for asset_info, ctx in zip(universe, asset_ctxs):
        base = str(asset_info.get("name", ""))
        if not base:
            continue

        trading_pair = f"{base}-USD"
        if trading_pair in exclude_pairs:
            continue

        category = _get_category(base)
        if config.category != "all" and category != config.category:
            continue

        # Parse live data from asset context
        try:
            mark_px = float(ctx.get("markPx", 0) or 0)
            prev_day_px = float(ctx.get("prevDayPx", 0) or 0)
            day_ntl_vlm = float(ctx.get("dayNtlVlm", 0) or 0)
            funding = float(ctx.get("funding", 0) or 0)
            oi = float(ctx.get("openInterest", 0) or 0)
            oracle_px = float(ctx.get("oraclePx", 0) or 0)
        except (TypeError, ValueError):
            continue

        if mark_px <= 0 or day_ntl_vlm < config.min_volume_usd:
            continue

        change_24h_pct = (
            _pct_change(mark_px, prev_day_px) if prev_day_px > 0 else 0
        )
        oi_usd = oi * mark_px

        pairs.append({
            "base_asset": base,
            "trading_pair": trading_pair,
            "category": category,
            "max_leverage": asset_info.get("maxLeverage", 1),
            "sz_decimals": asset_info.get("szDecimals", 2),
            "quote_volume": day_ntl_vlm,
            "last_price": mark_px,
            "oracle_price": oracle_px,
            "change_24h_pct": change_24h_pct,
            "funding_rate": funding,
            "open_interest_usd": round(oi_usd, 2),
        })

    if not pairs:
        cat_msg = f" (category: {config.category})" if config.category != "all" else ""
        return f"No pairs meet volume threshold of ${config.min_volume_usd:,.0f}{cat_msg}"

    # Sort by volume, take top_n for candle analysis
    pairs.sort(key=lambda p: p["quote_volume"], reverse=True)
    pairs = pairs[: config.top_n]

    logger.info(
        "HL scanner: %d perps, %d above $%s vol, analyzing top %d (%.0fms)",
        len(universe),
        len(pairs),
        f"{config.min_volume_usd:,.0f}",
        len(pairs),
        (time.monotonic() - t_meta) * 1000,
    )

    # ── Step 3: Fetch candles in parallel (direct Hyperliquid API) ───
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    async with aiohttp.ClientSession() as session:
        candle_tasks = [
            _fetch_candles_direct(
                coin=p["base_asset"],
                interval=config.interval,
                lookback_hours=config.lookback_hours,
                session=session,
                semaphore=semaphore,
            )
            for p in pairs
        ]
        candle_results = await asyncio.gather(*candle_tasks)

    t_candles = time.monotonic()

    # ── Step 4: Analyze each pair ────────────────────────────────────
    analyzed: list[dict[str, Any]] = []
    for pair, candles in zip(pairs, candle_results):
        if not candles:
            continue
        result = _analyze_pair(pair, candles, config.breakout_window)
        if result and result["bias"] != "NEUTRAL":
            analyzed.append(result)

    if not analyzed:
        return "No directional high-volatility candidates found"

    # ── Step 5: Rank and return ──────────────────────────────────────
    analyzed.sort(key=lambda r: r["score"], reverse=True)
    rows = analyzed[: config.candidates]
    text = _format_rows(rows)

    elapsed_ms = (time.monotonic() - t_start) * 1000
    logger.info(
        "HL scanner complete: %d candidates in %.0fms "
        "(meta=%.0fms, candles=%.0fms, analyze=%.0fms)",
        len(rows),
        elapsed_ms,
        (t_meta - t_start) * 1000,
        (t_candles - t_meta) * 1000,
        (time.monotonic() - t_candles) * 1000,
    )

    return RoutineResult(
        text=text,
        table_data=rows,
        table_columns=[
            "trading_pair",
            "bias",
            "score",
            "last_price",
            "change_24h_pct",
            "atr_pct",
            "momentum_pct",
            "quote_volume_usd",
            "funding_rate",
            "open_interest_usd",
            "max_leverage",
            "category",
            "pullback_level",
            "breakout_level",
            "breakdown_level",
            "invalid_long_level",
            "invalid_short_level",
        ],
        sections=[
            {"title": "summary", "content": text},
        ],
    )
