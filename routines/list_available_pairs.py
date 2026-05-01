"""List available trading pairs from an exchange's public API.

This routine queries the exchange directly to get the current list of tradeable pairs,
avoiding hardcoded lists that need manual maintenance.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from pydantic import BaseModel, Field
from telegram.ext import ContextTypes

from routines.base import RoutineResult

logger = logging.getLogger(__name__)

# Public API endpoints for various exchanges
EXCHANGE_ENDPOINTS = {
    "hyperliquid": "https://api.hyperliquid.xyz/info",
    "binance_perpetual": "https://fapi.binance.com/fapi/v1/exchangeInfo",
    "binance_spot": "https://api.binance.com/api/v3/exchangeInfo",
}


class Config(BaseModel):
    """Configuration for listing available pairs."""

    exchange: str = Field(
        default="hyperliquid",
        description="Exchange to query (hyperliquid, binance_perpetual, binance_spot)",
    )
    quote_asset: str = Field(
        default="USDT",
        description="Filter pairs by quote asset (e.g., USDT, USD, USDC)",
    )
    status_filter: str = Field(
        default="TRADING",
        description="Only include pairs with this status (TRADING, ACTIVE, etc.)",
    )


async def _fetch_hyperliquid_pairs(quote_asset: str) -> list[str]:
    """Fetch available pairs from Hyperliquid."""
    url = EXCHANGE_ENDPOINTS["hyperliquid"]
    payload = {"type": "meta"}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
    
    # Hyperliquid returns: {"universe": [{"name": "BTC", ...}, {"name": "ETH", ...}]}
    universe = data.get("universe", [])
    pairs = []
    
    for asset in universe:
        if isinstance(asset, dict):
            name = asset.get("name", "")
            if name:
                # Hyperliquid uses format like "BTC" -> convert to "BTC-USDT"
                pair = f"{name}-{quote_asset}"
                pairs.append(pair)
    
    return sorted(pairs)


async def _fetch_binance_pairs(endpoint: str, quote_asset: str, status_filter: str) -> list[str]:
    """Fetch available pairs from Binance (spot or perpetual)."""
    async with aiohttp.ClientSession() as session:
        async with session.get(endpoint) as resp:
            resp.raise_for_status()
            data = await resp.json()
    
    pairs = []
    symbols = data.get("symbols", [])
    
    for symbol_info in symbols:
        if not isinstance(symbol_info, dict):
            continue
        
        symbol = symbol_info.get("symbol", "")
        status = symbol_info.get("status", "")
        quote = symbol_info.get("quoteAsset", "")
        
        # Filter by quote asset and status
        if quote == quote_asset and status == status_filter:
            # Convert BTCUSDT -> BTC-USDT
            base = symbol_info.get("baseAsset", "")
            if base:
                pair = f"{base}-{quote}"
                pairs.append(pair)
    
    return sorted(pairs)


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    """Fetch and return list of available trading pairs from the exchange."""
    
    try:
        if config.exchange == "hyperliquid":
            pairs = await _fetch_hyperliquid_pairs(config.quote_asset)
        elif config.exchange in ["binance_perpetual", "binance_spot"]:
            endpoint = EXCHANGE_ENDPOINTS[config.exchange]
            pairs = await _fetch_binance_pairs(endpoint, config.quote_asset, config.status_filter)
        else:
            return f"Unsupported exchange: {config.exchange}"
        
        if not pairs:
            return f"No pairs found on {config.exchange} with quote asset {config.quote_asset}"
        
        # Format output
        summary = f"Found {len(pairs)} tradeable pairs on {config.exchange} ({config.quote_asset}):\n"
        summary += ", ".join(pairs[:20])
        if len(pairs) > 20:
            summary += f"\n... and {len(pairs) - 20} more"
        
        logger.info(f"Retrieved {len(pairs)} pairs from {config.exchange}")
        
        return RoutineResult(
            text=summary,
            table_data=[{"trading_pair": pair} for pair in pairs],
            table_columns=["trading_pair"],
            sections=[
                {
                    "title": "Available Pairs",
                    "content": f"Total: {len(pairs)} pairs\nSample: {', '.join(pairs[:10])}",
                }
            ],
        )
    
    except aiohttp.ClientError as exc:
        logger.error(f"Failed to fetch pairs from {config.exchange}: {exc}")
        return f"Network error while fetching pairs from {config.exchange}: {exc}"
    except Exception as exc:
        logger.error(f"Error fetching pairs from {config.exchange}: {exc}")
        return f"Error fetching pairs: {exc}"
