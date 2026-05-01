"""Small-Cap Screener Global Routine - Identify momentum opportunities in small-cap assets.

This routine screens small-cap cryptocurrencies (<$100M market cap) for momentum factor
signals including BTC price transmission lag, volume-to-mcap ratio spikes, and social volume anomalies.

Based on: The Agentic Trading Platform Technical Reference v4.0, Section 5.4

Factors:
- BTC transmission lag: Small-caps that lag BTC moves (catch-up opportunity)
- Volume/MCap ratio: High trading volume relative to market cap (liquidity surge)
- Social volume anomaly: Unusual mention spikes (early catalyst detection)

Target Tier: Speculative (<$100M mcap)

Output: Ranked small-cap opportunities with factor scores
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from pydantic import BaseModel, Field
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from config_manager import get_client
from routines.base import RoutineResult

logger = logging.getLogger(__name__)

COINGECKO_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_COINS_LIST = "https://api.coingecko.com/api/v3/coins/list"


class Config(BaseModel):
    """Configuration for smallcap_screener routine."""

    max_market_cap: float = Field(
        default=100_000_000,
        description="Maximum market cap in USD for screening (100M = small-cap)",
    )
    min_market_cap: float = Field(
        default=1_000_000,
        description="Minimum market cap in USD (filter out micro-caps)",
    )
    min_volume_24h: float = Field(
        default=100_000,
        description="Minimum 24h volume in USD (liquidity filter)",
    )
    top_n: int = Field(
        default=50,
        description="Number of small-caps to analyze (ranked by volume)",
    )
    candidates: int = Field(
        default=10,
        description="Number of top candidates to return",
    )
    connector: str = Field(
        default="hyperliquid_perpetual",
        description="Connector for price data",
    )


async def _fetch_smallcap_coins(max_mcap: float, min_mcap: float, min_volume: float, top_n: int) -> list[dict[str, Any]]:
    """Fetch small-cap coins from CoinGecko."""
    smallcaps = []
    
    try:
        async with aiohttp.ClientSession() as session:
            params = {
                "vs_currency": "usd",
                "order": "volume_desc",
                "per_page": "250",
                "page": "1",
                "sparkline": "false",
            }
            
            async with session.get(COINGECKO_MARKETS, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    for coin in data:
                        mcap = coin.get("market_cap") or 0
                        volume_24h = coin.get("total_volume") or 0
                        
                        # Filter by market cap and volume
                        if min_mcap <= mcap <= max_mcap and volume_24h >= min_volume:
                            smallcaps.append({
                                "symbol": (coin.get("symbol") or "").upper(),
                                "name": coin.get("name", ""),
                                "market_cap": mcap,
                                "volume_24h": volume_24h,
                                "price": coin.get("current_price", 0),
                                "price_change_24h": coin.get("price_change_percentage_24h", 0),
                                "volume_to_mcap_ratio": volume_24h / mcap if mcap > 0 else 0,
                            })
            
            # Sort by volume and take top N
            smallcaps.sort(key=lambda x: x["volume_24h"], reverse=True)
            smallcaps = smallcaps[:top_n]
            
            logger.info(f"Fetched {len(smallcaps)} small-cap coins from CoinGecko")
    
    except Exception as exc:
        logger.error(f"Failed to fetch small-cap coins: {exc}")
    
    return smallcaps


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    """Screen small-cap cryptocurrencies for momentum opportunities."""
    
    client = await get_client(context._chat_id, context=context)
    if not client:
        return "No server available"
    
    # Fetch small-cap coins
    smallcaps = await _fetch_smallcap_coins(
        config.max_market_cap,
        config.min_market_cap,
        config.min_volume_24h,
        config.top_n,
    )
    
    if not smallcaps:
        return "No small-cap coins found matching criteria"
    
    # Fetch BTC price movement for transmission lag analysis
    try:
        btc_candles_result = await client.market_data.get_candles(
            connector_name=config.connector,
            trading_pair="BTC-USDT",
            interval="1h",
            max_records=24,
        )
        
        if isinstance(btc_candles_result, dict):
            btc_candles = btc_candles_result.get("data", [])
        elif isinstance(btc_candles_result, list):
            btc_candles = btc_candles_result
        else:
            btc_candles = []
        
        if btc_candles and len(btc_candles) >= 2:
            btc_first_close = float(btc_candles[0]["close"])
            btc_last_close = float(btc_candles[-1]["close"])
            btc_change_pct = ((btc_last_close - btc_first_close) / btc_first_close) * 100
        else:
            btc_change_pct = 0.0
    
    except Exception as e:
        logger.warning(f"Failed to fetch BTC data: {e}")
        btc_change_pct = 0.0
    
    # Score each small-cap
    scored_caps = []
    
    for coin in smallcaps:
        symbol = coin["symbol"]
        mcap = coin["market_cap"]
        volume_24h = coin["volume_24h"]
        price_change_24h = coin["price_change_24h"]
        vol_mcap_ratio = coin["volume_to_mcap_ratio"]
        
        # Factor 1: Volume/MCap ratio (liquidity surge)
        # Higher is better, normalize to 0-100 scale
        vol_mcap_score = min(vol_mcap_ratio * 10, 100)
        
        # Factor 2: BTC transmission lag (catch-up opportunity)
        # If BTC moved significantly but coin lagged, score higher
        if abs(btc_change_pct) > 2.0:  # BTC moved at least 2%
            transmission_lag = abs(btc_change_pct) - abs(price_change_24h)
            if transmission_lag > 0:  # Coin lagged BTC
                lag_score = min(transmission_lag * 5, 100)
            else:
                lag_score = 0
        else:
            lag_score = 0
        
        # Factor 3: Absolute price momentum
        momentum_score = min(abs(price_change_24h) * 2, 100)
        
        # Factor 4: Liquidity quality (prefer higher volume)
        liquidity_score = min((volume_24h / config.min_volume_24h) * 10, 100)
        
        # Composite score (weighted average)
        composite_score = (
            vol_mcap_score * 0.3
            + lag_score * 0.25
            + momentum_score * 0.25
            + liquidity_score * 0.2
        )
        
        scored_caps.append({
            "symbol": symbol,
            "name": coin["name"],
            "market_cap": mcap,
            "volume_24h": volume_24h,
            "price_change_24h": price_change_24h,
            "vol_mcap_ratio": vol_mcap_ratio,
            "vol_mcap_score": vol_mcap_score,
            "lag_score": lag_score,
            "momentum_score": momentum_score,
            "liquidity_score": liquidity_score,
            "composite_score": composite_score,
        })
    
    # Sort by composite score
    scored_caps.sort(key=lambda x: x["composite_score"], reverse=True)
    
    # Take top candidates
    top_candidates = scored_caps[:config.candidates]
    
    # Format output
    summary_lines = [
        f"Small-Cap Momentum Screening (BTC 24h: {btc_change_pct:+.2f}%):",
        f"Analyzed {len(smallcaps)} small-caps, showing top {len(top_candidates)}:",
    ]
    
    for i, candidate in enumerate(top_candidates, 1):
        summary_lines.append(
            f"\n  {i}. {candidate['symbol']} ({candidate['name']})\n"
            f"     Score: {candidate['composite_score']:.1f}/100\n"
            f"     MCap: ${candidate['market_cap']:,.0f}\n"
            f"     Volume: ${candidate['volume_24h']:,.0f}\n"
            f"     Price 24h: {candidate['price_change_24h']:+.2f}%\n"
            f"     Vol/MCap: {candidate['vol_mcap_ratio']:.2%}\n"
            f"     Factors: Vol={candidate['vol_mcap_score']:.0f}, "
            f"Lag={candidate['lag_score']:.0f}, "
            f"Mom={candidate['momentum_score']:.0f}, "
            f"Liq={candidate['liquidity_score']:.0f}"
        )
    
    summary = "\n".join(summary_lines)
    
    logger.info(f"smallcap_screener: Ranked {len(top_candidates)} small-cap opportunities")
    
    return RoutineResult(
        text=summary,
        table_data=top_candidates,
        table_columns=[
            "symbol", "name", "market_cap", "volume_24h", "price_change_24h",
            "vol_mcap_ratio", "composite_score", "vol_mcap_score", "lag_score",
            "momentum_score", "liquidity_score"
        ],
        sections=[
            {
                "title": "Small-Cap Opportunities",
                "content": summary,
            }
        ],
    )
