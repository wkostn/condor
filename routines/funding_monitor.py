"""Funding Monitor Global Routine - Track derivatives market data.

This routine fetches funding rates, open interest, long/short ratio, and
liquidation clusters for perpetual futures. Critical for assessing market
positioning and identifying liquidation cascade risks.

Based on: The Agentic Trading Platform Technical Reference v4.0, Section 5.4

Data Sources:
- Binance Futures API: funding rates, OI, long/short ratio
- Coinglass API: liquidation heatmaps (if available)

Output: Derivatives data per asset for risk assessment
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from pydantic import BaseModel, Field
from telegram.ext import ContextTypes

from routines.base import RoutineResult

logger = logging.getLogger(__name__)

BINANCE_PREMIUM_INDEX = "https://fapi.binance.com/fapi/v1/premiumIndex"
BINANCE_OPEN_INTEREST = "https://fapi.binance.com/fapi/v1/openInterest"
BINANCE_LONG_SHORT_RATIO = "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
BINANCE_LIQUIDATIONS = "https://fapi.binance.com/fapi/v1/forceOrders"


class Config(BaseModel):
    """Configuration for funding_monitor routine."""

    trading_pairs: list[str] = Field(
        default_factory=lambda: ["BTC-USDT", "ETH-USDT", "SOL-USDT"],
        description="List of pairs to monitor",
    )
    high_funding_threshold: float = Field(
        default=0.01,
        description="Funding rate % threshold to flag as high (0.01 = 1%)",
    )
    lookback_hours: int = Field(
        default=24,
        description="Hours to lookback for liquidation data",
    )


async def _fetch_funding_rates(pairs: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch current funding rates from Binance."""
    funding_data = {}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(BINANCE_PREMIUM_INDEX, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                data = await resp.json()
        
        for item in data:
            symbol = item.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue
            
            base = symbol[:-4]
            pair = f"{base}-USDT"
            
            if pair in pairs:
                funding_rate = float(item.get("lastFundingRate", 0) or 0)
                next_funding_time = int(item.get("nextFundingTime", 0) or 0)
                mark_price = float(item.get("markPrice", 0) or 0)
                
                # Convert to percentage (funding rate is per 8 hours)
                funding_rate_pct = funding_rate * 100
                
                # Annualized (3 times per day * 365 days)
                annualized_pct = funding_rate_pct * 3 * 365
                
                funding_data[pair] = {
                    "funding_rate": funding_rate,
                    "funding_rate_pct": round(funding_rate_pct, 4),
                    "annualized_pct": round(annualized_pct, 2),
                    "next_funding_time": datetime.fromtimestamp(next_funding_time / 1000) if next_funding_time else None,
                    "mark_price": mark_price,
                }
        
        logger.info(f"Fetched funding rates for {len(funding_data)} pairs")
    
    except Exception as exc:
        logger.error(f"Failed to fetch funding rates: {exc}")
    
    return funding_data


async def _fetch_open_interest(pairs: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch open interest from Binance."""
    oi_data = {}
    
    try:
        async with aiohttp.ClientSession() as session:
            for pair in pairs:
                symbol = pair.replace("-", "")  # BTC-USDT -> BTCUSDT
                
                try:
                    async with session.get(
                        BINANCE_OPEN_INTEREST,
                        params={"symbol": symbol},
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            oi_value = float(data.get("openInterest", 0) or 0)
                            
                            oi_data[pair] = {
                                "open_interest": oi_value,
                                "timestamp": datetime.now(),
                            }
                except Exception as e:
                    logger.debug(f"Failed to fetch OI for {pair}: {e}")
                    continue
        
        logger.info(f"Fetched open interest for {len(oi_data)} pairs")
    
    except Exception as exc:
        logger.error(f"Failed to fetch open interest: {exc}")
    
    return oi_data


async def _fetch_long_short_ratio(pairs: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch long/short account ratio from Binance."""
    ls_data = {}
    
    try:
        async with aiohttp.ClientSession() as session:
            for pair in pairs:
                symbol = pair.replace("-", "")  # BTC-USDT -> BTCUSDT
                
                try:
                    async with session.get(
                        BINANCE_LONG_SHORT_RATIO,
                        params={
                            "symbol": symbol,
                            "period": "5m",
                            "limit": 1,
                        },
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data:
                                latest = data[0]
                                long_ratio = float(latest.get("longAccount", 0) or 0)
                                short_ratio = float(latest.get("shortAccount", 0) or 0)
                                
                                ls_data[pair] = {
                                    "long_account_ratio": long_ratio,
                                    "short_account_ratio": short_ratio,
                                    "long_short_ratio": round(long_ratio / short_ratio, 2) if short_ratio > 0 else 0,
                                }
                except Exception as e:
                    logger.debug(f"Failed to fetch L/S ratio for {pair}: {e}")
                    continue
        
        logger.info(f"Fetched long/short ratios for {len(ls_data)} pairs")
    
    except Exception as exc:
        logger.error(f"Failed to fetch long/short ratios: {exc}")
    
    return ls_data


async def _fetch_liquidations(pairs: list[str], lookback_hours: int) -> dict[str, list[dict[str, Any]]]:
    """Fetch recent liquidation data from Binance."""
    liq_data = {}
    
    try:
        start_time = int((datetime.now() - timedelta(hours=lookback_hours)).timestamp() * 1000)
        
        async with aiohttp.ClientSession() as session:
            for pair in pairs:
                symbol = pair.replace("-", "")  # BTC-USDT -> BTCUSDT
                
                try:
                    async with session.get(
                        BINANCE_LIQUIDATIONS,
                        params={
                            "symbol": symbol,
                            "startTime": start_time,
                            "limit": 100,
                        },
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            
                            liquidations = []
                            total_liq_value = 0
                            
                            for liq in data:
                                side = liq.get("side", "")
                                price = float(liq.get("price", 0) or 0)
                                qty = float(liq.get("origQty", 0) or 0)
                                time_ms = int(liq.get("time", 0) or 0)
                                
                                value = price * qty
                                total_liq_value += value
                                
                                liquidations.append({
                                    "side": side,
                                    "price": price,
                                    "quantity": qty,
                                    "value_usd": value,
                                    "timestamp": datetime.fromtimestamp(time_ms / 1000),
                                })
                            
                            liq_data[pair] = {
                                "liquidations": liquidations,
                                "total_liquidated_usd": round(total_liq_value, 2),
                                "count": len(liquidations),
                            }
                
                except Exception as e:
                    logger.debug(f"Failed to fetch liquidations for {pair}: {e}")
                    continue
        
        logger.info(f"Fetched liquidation data for {len(liq_data)} pairs")
    
    except Exception as exc:
        logger.error(f"Failed to fetch liquidations: {exc}")
    
    return liq_data


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    """Fetch derivatives market data for specified pairs."""
    
    # Fetch all data in parallel
    funding_task = _fetch_funding_rates(config.trading_pairs)
    oi_task = _fetch_open_interest(config.trading_pairs)
    ls_task = _fetch_long_short_ratio(config.trading_pairs)
    liq_task = _fetch_liquidations(config.trading_pairs, config.lookback_hours)
    
    funding_data, oi_data, ls_data, liq_data = await asyncio.gather(
        funding_task, oi_task, ls_task, liq_task,
        return_exceptions=False
    )
    
    # Merge all data
    merged_data = {}
    
    for pair in config.trading_pairs:
        merged_data[pair] = {
            "funding": funding_data.get(pair, {}),
            "open_interest": oi_data.get(pair, {}),
            "long_short": ls_data.get(pair, {}),
            "liquidations": liq_data.get(pair, {}),
        }
    
    # Format output
    summary_lines = ["Derivatives Market Data:"]
    table_data = []
    high_funding_pairs = []
    
    for pair, data in sorted(merged_data.items()):
        funding = data["funding"]
        oi = data["open_interest"]
        ls = data["long_short"]
        liq = data["liquidations"]
        
        funding_pct = funding.get("funding_rate_pct", 0)
        annualized = funding.get("annualized_pct", 0)
        oi_value = oi.get("open_interest", 0)
        ls_ratio = ls.get("long_short_ratio", 0)
        total_liq = liq.get("total_liquidated_usd", 0)
        liq_count = liq.get("count", 0)
        
        # Flag high funding
        flag = ""
        if abs(funding_pct) >= config.high_funding_threshold:
            direction = "LONG paying SHORT" if funding_pct > 0 else "SHORT paying LONG"
            high_funding_pairs.append(f"{pair} ({direction})")
            flag = " ⚠️"
        
        summary_lines.append(
            f"  {pair}:\n"
            f"    Funding: {funding_pct:+.4f}% (~{annualized:+.1f}% APR){flag}\n"
            f"    OI: {oi_value:,.0f} contracts\n"
            f"    L/S Ratio: {ls_ratio:.2f}\n"
            f"    Liquidations ({config.lookback_hours}h): ${total_liq:,.0f} ({liq_count} events)"
        )
        
        table_data.append({
            "trading_pair": pair,
            "funding_rate_pct": funding_pct,
            "annualized_pct": annualized,
            "open_interest": oi_value,
            "long_short_ratio": ls_ratio,
            "liquidations_24h_usd": total_liq,
            "liquidation_count": liq_count,
            "high_funding": abs(funding_pct) >= config.high_funding_threshold,
        })
    
    summary = "\n".join(summary_lines)
    
    if high_funding_pairs:
        summary += f"\n\n⚠️ High funding: {', '.join(high_funding_pairs)}"
    
    logger.info(f"funding_monitor: Compiled derivatives data for {len(merged_data)} pairs")
    
    return RoutineResult(
        text=summary,
        table_data=table_data,
        table_columns=[
            "trading_pair", "funding_rate_pct", "annualized_pct",
            "open_interest", "long_short_ratio", "liquidations_24h_usd",
            "liquidation_count", "high_funding"
        ],
        sections=[
            {
                "title": "Derivatives Market Summary",
                "content": summary,
            }
        ],
    )
