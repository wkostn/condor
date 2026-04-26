"""Morning Scan Global Routine - Full market screening for trading opportunities.

This routine runs daily at 06:00 UTC and screens the entire cryptocurrency market
for high-volatility movers across all market cap tiers. It produces MarketState objects
that serve as input for the LLM Decision Engine.

Based on: The Agentic Trading Platform Technical Reference v4.0, Section 5.1

Workflow:
1. Fetch top 50 pairs by 24h volume from Binance Futures
2. Fetch market cap data from CoinGecko API
3. Classify each pair into market cap tiers (Core/Growth/Speculative/High-Risk)
4. Fetch candle data and compute technical indicators (basic)
5. Calculate opportunity score for each pair
6. Return List[MarketState] sorted by opportunity_score

This routine replaces/extends high_vol_coin_levels with:
- Broader coverage (50 vs 20 pairs)
- Market cap classification
- Structured MarketState output
- Scheduled execution (not continuous)
"""

from __future__ import annotations

import asyncio
import logging
import math
import statistics
from datetime import datetime
from typing import Any

import aiohttp
from pydantic import BaseModel, Field, field_validator
from telegram.ext import ContextTypes

from config_manager import get_client
from routines.base import RoutineResult
from schemas.market_state import MarketState, TechnicalIndicators
from routines.tech_overlay import compute_technical_indicators

logger = logging.getLogger(__name__)

BINANCE_FUTURES_TICKER = "https://fapi.binance.com/fapi/v1/ticker/24hr"
COINGECKO_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"
MAX_CONCURRENT = 8


class Config(BaseModel):
    """Configuration for morning_scan routine."""

    connector: str = Field(
        default="hyperliquid_perpetual",
        description="Perpetual connector for candle data"
    )
    top_n: int = Field(
        default=50,
        description="Top markets by 24h volume to scan"
    )
    candidates: int = Field(
        default=20,
        description="How many top candidates to return"
    )
    interval: str = Field(
        default="5m",
        description="Candle interval for analysis"
    )
    max_records: int = Field(
        default=72,
        description="Candles to fetch per market"
    )
    breakout_window: int = Field(
        default=12,
        description="Recent candles for breakout/breakdown levels"
    )
    min_volume_usd: float = Field(
        default=25_000_000,
        description="Minimum 24h volume in USD"
    )
    exclude_pairs: list[str] = Field(
        default_factory=list,
        description="Pairs to exclude from scan"
    )
    coingecko_vs_currency: str = Field(
        default="usd",
        description="CoinGecko currency for market cap"
    )

    @field_validator("exclude_pairs", mode="before")
    @classmethod
    def normalize_exclude_pairs(cls, v):
        return v if v is not None else []


# ==================== Market Cap Fetching ====================

async def _fetch_market_caps_coingecko(
    symbols: list[str],
    vs_currency: str = "usd"
) -> dict[str, float]:
    """Fetch market caps from CoinGecko API.
    
    Args:
        symbols: List of base symbols (BTC, ETH, etc.)
        vs_currency: Currency for market cap (usd, eur, etc.)
    
    Returns:
        Dict mapping symbol -> market_cap in USD
    """
    # CoinGecko free tier: 10-50 calls/minute
    # We'll batch this into a single request using /coins/markets endpoint
    
    try:
        params = {
            "vs_currency": vs_currency,
            "order": "market_cap_desc",
            "per_page": 250,  # Get top 250 to ensure coverage
            "page": 1,
            "sparkline": "false",
            "locale": "en"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(COINGECKO_MARKETS, params=params, timeout=10) as resp:
                if resp.status != 200:
                    logger.warning(f"CoinGecko API returned {resp.status}")
                    return {}
                data = await resp.json()
        
        # Build symbol -> market_cap mapping
        market_caps = {}
        for coin in data:
            symbol = coin.get("symbol", "").upper()
            market_cap = coin.get("market_cap")
            if symbol and market_cap:
                market_caps[symbol] = float(market_cap)
        
        logger.info(f"Fetched market caps for {len(market_caps)} assets from CoinGecko")
        return market_caps
        
    except Exception as exc:
        logger.error(f"Failed to fetch market caps from CoinGecko: {exc}")
        return {}


def _classify_tier(market_cap: float) -> str:
    """Classify asset into market cap tier.
    
    Tier definitions from Technical Reference Section 8.2:
    - Core: > $10B (BTC, ETH)
    - Growth: $500M - $10B (mid-cap altcoins)
    - Speculative: $100M - $500M (small-cap, RWA)
    - High-Risk: < $100M (meme coins, new launches)
    """
    if market_cap >= 10_000_000_000:  # >= $10B
        return "core"
    elif market_cap >= 500_000_000:  # $500M - $10B
        return "growth"
    elif market_cap >= 100_000_000:  # $100M - $500M
        return "speculative"
    else:  # < $100M
        return "high_risk"


# ==================== Price/Volume Fetching ====================

async def _fetch_top_pairs(
    top_n: int,
    min_volume_usd: float,
    exclude_pairs: set[str]
) -> list[dict[str, Any]]:
    """Fetch top perpetual pairs by 24h volume from Binance Futures."""
    
    async with aiohttp.ClientSession() as session:
        async with session.get(BINANCE_FUTURES_TICKER, timeout=10) as resp:
            resp.raise_for_status()
            payload = await resp.json()

    pairs: list[dict[str, Any]] = []
    for item in payload:
        symbol = str(item.get("symbol", ""))
        if not symbol.endswith("USDT"):
            continue
        
        base = symbol[:-4]  # Remove USDT suffix
        trading_pair = f"{base}-USDT"
        
        if trading_pair in exclude_pairs:
            continue

        quote_volume = float(item.get("quoteVolume", 0) or 0)
        if quote_volume < min_volume_usd:
            continue

        pairs.append({
            "symbol": symbol,
            "base": base,
            "trading_pair": trading_pair,
            "quote_volume": quote_volume,
            "last_price": float(item.get("lastPrice", 0) or 0),
            "change_24h_pct": float(item.get("priceChangePercent", 0) or 0),
            "volume_24h": quote_volume,  # Already in USD
        })

    pairs.sort(key=lambda row: row["quote_volume"], reverse=True)
    return pairs[:top_n]


# ==================== Candle Data & Analysis ====================

async def _fetch_candles(
    client: Any,
    connector: str,
    trading_pair: str,
    interval: str,
    max_records: int,
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]] | None:
    """Fetch candle data for a single pair."""
    
    async with semaphore:
        try:
            result = await client.market_data.get_candles(
                connector_name=connector,
                trading_pair=trading_pair,
                interval=interval,
                max_records=max_records,
            )
        except Exception as exc:
            logger.debug(f"Candle fetch failed for {trading_pair}: {exc}")
            return None

    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        data = result.get("data")
        return data if isinstance(data, list) else None
    return None


def _ema(values: list[float], period: int) -> float:
    """Calculate Exponential Moving Average."""
    if not values:
        return 0.0
    alpha = 2 / (period + 1)
    ema_value = values[0]
    for value in values[1:]:
        ema_value = value * alpha + ema_value * (1 - alpha)
    return ema_value


def _atr_pct(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14
) -> float:
    """Calculate ATR as percentage of price."""
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
    """Calculate percentage change."""
    if previous == 0:
        return 0.0
    return ((current - previous) / previous) * 100


def _compute_opportunity_score(
    volume_24h: float,
    price_change_24h: float,
    atr_pct: float,
    tier: str,
    momentum_pct: float,
    realized_vol_pct: float
) -> float:
    """Calculate opportunity score (0-1) for ranking.
    
    Scoring weights:
    - ATR: 35% (volatility = opportunity)
    - Volume: 25% (liquidity = tradeable)
    - Momentum: 20% (directional move)
    - Realized Vol: 20% (recent volatility)
    
    Adjustments by tier:
    - Core: Require higher volume, lower volatility acceptable
    - Growth: Balanced requirements
    - Speculative: More flexible on volume, higher vol preferred
    - High-Risk: Very flexible, emphasize momentum
    """
    
    # Base scoring
    atr_score = min(atr_pct / 5.0, 1.0)  # Normalize: 5% ATR = max
    volume_score = min(volume_24h / 500_000_000, 1.0)  # $500M = max
    momentum_score = min(abs(momentum_pct) / 10.0, 1.0)  # 10% = max
    vol_score = min(realized_vol_pct / 100.0, 1.0)  # 100% realized vol = max
    
    # Tier-specific weighting
    if tier == "core":
        weights = (0.25, 0.40, 0.15, 0.20)  # Emphasize volume
    elif tier == "growth":
        weights = (0.35, 0.25, 0.20, 0.20)  # Balanced
    elif tier == "speculative":
        weights = (0.40, 0.15, 0.25, 0.20)  # Emphasize vol + momentum
    else:  # high_risk
        weights = (0.35, 0.10, 0.35, 0.20)  # Emphasize momentum
    
    raw_score = (
        atr_score * weights[0] +
        volume_score * weights[1] +
        momentum_score * weights[2] +
        vol_score * weights[3]
    )
    
    return min(raw_score, 1.0)


def _analyze_pair_to_market_state(
    pair: dict[str, Any],
    candles: list[dict[str, Any]],
    market_cap: float,
    tier: str,
    breakout_window: int,
    compute_technicals: bool = True
) -> MarketState | None:
    """Analyze a pair and convert to MarketState object.
    
    This is the core analysis function that produces structured MarketState objects
    for the LLM Decision Engine.
    
    Args:
        pair: Pair metadata (symbol, volume, etc.)
        candles: OHLCV candle data
        market_cap: Market capitalization in USD
        tier: Market cap tier classification
        breakout_window: Candles for level calculation
        compute_technicals: Whether to compute full technical indicators (default: True)
    """
    
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

    # Compute levels
    one_hour_high = max(highs[-breakout_window:])
    one_hour_low = min(lows[-breakout_window:])
    four_hour_high = max(highs[-48:]) if len(highs) >= 48 else max(highs)
    four_hour_low = min(lows[-48:]) if len(lows) >= 48 else min(lows)
    
    momentum_pct = _pct_change(last_price, closes[-breakout_window - 1])

    # Realized volatility
    returns: list[float] = []
    for idx in range(1, len(closes)):
        prev = closes[idx - 1]
        if prev > 0:
            returns.append((closes[idx] - prev) / prev)
    realized_vol_pct = (
        statistics.pstdev(returns[-24:]) * math.sqrt(max(len(returns[-24:]), 1)) * 100
        if returns else 0.0
    )

    # Trend direction
    if ema_fast > ema_slow and last_price >= ema_fast and momentum_pct > 0:
        trend_direction = "bullish"
    elif ema_fast < ema_slow and last_price <= ema_fast and momentum_pct < 0:
        trend_direction = "bearish"
    else:
        trend_direction = "neutral"

    # Compute opportunity score
    opportunity_score = _compute_opportunity_score(
        volume_24h=pair["volume_24h"],
        price_change_24h=pair["change_24h_pct"],
        atr_pct=atr_pct,
        tier=tier,
        momentum_pct=momentum_pct,
        realized_vol_pct=realized_vol_pct
    )

    # Compute full technical indicators if requested
    technical_indicators = None
    if compute_technicals:
        technical_indicators = compute_technical_indicators(candles)

    # Build MarketState
    return MarketState(
        timestamp=datetime.utcnow(),
        asset=pair["base"],
        trading_pair=pair["trading_pair"],
        market_cap_tier=tier,
        market_cap=market_cap,
        
        # Price & Volume
        price=last_price,
        price_change_24h=pair["change_24h_pct"],
        volume_24h=pair["volume_24h"],
        volume_change_24h=0.0,  # Would need historical data
        
        # Technical indicators (populated by tech_overlay)
        technical=technical_indicators,
        
        # Opportunity scoring
        opportunity_score=opportunity_score,
    )


# ==================== Main Routine ====================

async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    """Run the morning scan routine.
    
    Returns:
        RoutineResult with MarketState objects in table_data
    """
    
    logger.info("🌅 Starting morning_scan routine")
    
    # Get Hummingbot client
    client = await get_client(context._chat_id, context=context)
    if not client:
        return "No Hummingbot server available"

    # Step 1: Fetch top pairs by volume
    exclude_pairs = {pair.upper() for pair in config.exclude_pairs}
    top_pairs = await _fetch_top_pairs(config.top_n, config.min_volume_usd, exclude_pairs)
    
    if not top_pairs:
        return "No liquid pairs found meeting volume criteria"
    
    logger.info(f"📊 Found {len(top_pairs)} pairs meeting volume criteria")

    # Step 2: Fetch market caps from CoinGecko
    symbols = [pair["base"] for pair in top_pairs]
    market_caps = await _fetch_market_caps_coingecko(symbols, config.coingecko_vs_currency)
    
    # Default market cap if not found (treat as high-risk)
    default_market_cap = 50_000_000  # $50M = high-risk tier

    # Step 3: Classify tiers
    for pair in top_pairs:
        mc = market_caps.get(pair["base"], default_market_cap)
        pair["market_cap"] = mc
        pair["tier"] = _classify_tier(mc)
    
    # Log tier distribution
    tier_counts = {}
    for pair in top_pairs:
        tier = pair["tier"]
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    logger.info(f"📈 Tier distribution: {tier_counts}")

    # Step 4: Fetch candles and analyze
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

    # Step 5: Build MarketState objects
    market_states: list[MarketState] = []
    for pair, candles in zip(top_pairs, candle_results):
        if not candles:
            continue
        
        market_state = _analyze_pair_to_market_state(
            pair=pair,
            candles=candles,
            market_cap=pair["market_cap"],
            tier=pair["tier"],
            breakout_window=config.breakout_window
        )
        
        if market_state:
            market_states.append(market_state)

    if not market_states:
        return "No viable opportunities found after analysis"

    # Step 6: Sort by opportunity score and take top N
    market_states.sort(key=lambda ms: ms.opportunity_score, reverse=True)
    top_candidates = market_states[:config.candidates]
    
    logger.info(f"✅ Morning scan complete: {len(top_candidates)} top opportunities identified")

    # Format output
    summary_lines = ["🌅 Morning Scan Results\n"]
    for idx, ms in enumerate(top_candidates, start=1):
        summary_lines.append(
            f"{idx}. {ms.get_summary()}"
        )
    summary_text = "\n".join(summary_lines)

    return RoutineResult(
        text=summary_text,
        table_data=[
            {
                "trading_pair": ms.trading_pair,
                "tier": ms.market_cap_tier,
                "price": ms.price,
                "change_24h": ms.price_change_24h,
                "volume_24h": ms.volume_24h,
                "market_cap": ms.market_cap,
                "opportunity_score": ms.opportunity_score,
            }
            for ms in top_candidates
        ],
        table_columns=[
            "trading_pair",
            "tier",
            "price",
            "change_24h",
            "volume_24h",
            "market_cap",
            "opportunity_score",
        ],
        sections=[
            {
                "title": "Morning Scan Summary",
                "content": summary_text,
            },
            {
                "title": "Tier Distribution",
                "content": f"Core: {tier_counts.get('core', 0)}, "
                          f"Growth: {tier_counts.get('growth', 0)}, "
                          f"Speculative: {tier_counts.get('speculative', 0)}, "
                          f"High-Risk: {tier_counts.get('high_risk', 0)}"
            }
        ],
    )
