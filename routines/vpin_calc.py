"""VPIN Calculator Global Routine - Volume-synchronized Probability of Informed Trading.

This routine implements VPIN (Easley, López de Prado, O'Hara 2012) to detect toxic
order flow and predict flash crashes or volatility events.

Based on: The Agentic Trading Platform Technical Reference v4.0, Section 5.3

Methodology:
- Analyze order flow imbalance within fixed-volume buckets
- Output score from 0 to 1 (>0.7 = high toxicity)
- Uses Hummingbot's MarketDataProvider for real-time data

Note: Simplified implementation using trade direction from price changes.
Full implementation would require tick data with bid/ask context.

Output: VPIN score per asset for order flow toxicity assessment
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from typing import Any

from pydantic import BaseModel, Field, field_validator
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from config_manager import get_client
from routines.base import RoutineResult

logger = logging.getLogger(__name__)


class Config(BaseModel):
    """Configuration for vpin_calc routine."""

    trading_pairs: list[str] = Field(
        default_factory=lambda: [
            "BTC-USD", "ETH-USD", "SOL-USD", "DOGE-USD", "XRP-USD",
            "AVAX-USD", "MATIC-USD", "LINK-USD", "UNI-USD", "ATOM-USD"
        ],
        description="List of pairs to analyze (Hyperliquid USD format)",
    )
    connector: str = Field(
        default="hyperliquid_perpetual",
        description="Connector to use for trade data",
    )
    num_buckets: int = Field(
        default=50,
        description="Number of volume buckets for VPIN calculation",
    )
    bucket_volume_usd: float = Field(
        default=500_000,
        description="Target USD volume per bucket (lowered for mid-cap coins)",
    )
    high_vpin_threshold: float = Field(
        default=0.7,
        description="VPIN threshold to flag as high toxicity (0-1 scale)",
    )

    @field_validator("trading_pairs", mode="before")
    @classmethod
    def normalize_trading_pairs(cls, v):
        """Convert None or string to list for web UI compatibility.
        
        Web UI may send: '["BTC-USD"]' as string instead of list.
        """
        if v is None:
            return []
        if isinstance(v, str):
            import json
            try:
                # Try parsing as JSON first
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, ValueError):
                # If not JSON, treat as comma-separated
                return [s.strip() for s in v.split(",") if s.strip()]
        return v if isinstance(v, list) else []


def _calculate_vpin_from_trades(trades: list[dict[str, Any]], bucket_volume: float) -> float:
    """Calculate VPIN from trade data.
    
    Simplified implementation that uses price direction to infer trade side.
    Full implementation would use tick rule or bid/ask comparison.
    """
    if not trades or len(trades) < 10:
        return 0.0
    
    # Create volume buckets
    buckets = []
    current_bucket = {"buy_volume": 0.0, "sell_volume": 0.0}
    
    for i, trade in enumerate(trades):
        price = trade.get("price", 0)
        volume = trade.get("volume", 0)
        value = price * volume
        
        if value == 0:
            continue
        
        # Infer trade direction from price change (simplified)
        if i > 0:
            prev_price = trades[i-1].get("price", price)
            if price > prev_price:
                side = "buy"
            elif price < prev_price:
                side = "sell"
            else:
                side = "neutral"
        else:
            side = "neutral"
        
        # Add to bucket
        if side == "buy":
            current_bucket["buy_volume"] += value
        elif side == "sell":
            current_bucket["sell_volume"] += value
        else:
            # Neutral trades split 50/50
            current_bucket["buy_volume"] += value / 2
            current_bucket["sell_volume"] += value / 2
        
        # Check if bucket is full
        total_bucket_volume = current_bucket["buy_volume"] + current_bucket["sell_volume"]
        if total_bucket_volume >= bucket_volume:
            buckets.append(current_bucket)
            current_bucket = {"buy_volume": 0.0, "sell_volume": 0.0}
    
    # Add final bucket if it has volume
    if current_bucket["buy_volume"] + current_bucket["sell_volume"] > 0:
        buckets.append(current_bucket)
    
    if not buckets:
        return 0.0
    
    # Calculate order imbalance for each bucket
    imbalances = []
    for bucket in buckets:
        total = bucket["buy_volume"] + bucket["sell_volume"]
        if total > 0:
            imbalance = abs(bucket["buy_volume"] - bucket["sell_volume"]) / total
            imbalances.append(imbalance)
    
    # VPIN is the average order imbalance across buckets
    if imbalances:
        vpin = statistics.mean(imbalances)
        return min(vpin, 1.0)
    
    return 0.0


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    """Calculate VPIN for specified trading pairs."""
    
    client = await get_client(context._chat_id, context=context)
    if not client:
        return "No server available"
    
    summary_lines = ["VPIN (Order Flow Toxicity) Analysis:"]
    table_data = []
    
    for pair in config.trading_pairs:
        try:
            # Fetch recent candles as proxy for trade data
            # (In production, would use actual trade stream)
            candles_result = await client.market_data.get_candles(
                connector_name=config.connector,
                trading_pair=pair,
                interval="1m",
                max_records=200,
            )
            
            if isinstance(candles_result, dict):
                candles = candles_result.get("data", [])
            elif isinstance(candles_result, list):
                candles = candles_result
            else:
                logger.warning(f"Invalid candle data format for {pair}")
                continue
            
            if not candles or len(candles) < 50:
                logger.warning(f"Insufficient data for {pair}: {len(candles)} candles")
                continue
            
            # Convert candles to pseudo-trades
            trades = []
            for candle in candles:
                # Use OHLC to generate multiple "trades" per candle
                open_price = float(candle.get("open", 0))
                high_price = float(candle.get("high", 0))
                low_price = float(candle.get("low", 0))
                close_price = float(candle.get("close", 0))
                volume = float(candle.get("volume", 0))
                
                if volume > 0:
                    # Create pseudo-trades at different price points
                    trades.extend([
                        {"price": open_price, "volume": volume / 4},
                        {"price": high_price, "volume": volume / 4},
                        {"price": low_price, "volume": volume / 4},
                        {"price": close_price, "volume": volume / 4},
                    ])
            
            # Calculate VPIN
            vpin_score = _calculate_vpin_from_trades(trades, config.bucket_volume_usd)
            
            # Determine toxicity level
            if vpin_score >= config.high_vpin_threshold:
                toxicity_label = "HIGH ⚠️"
            elif vpin_score >= 0.5:
                toxicity_label = "MODERATE"
            else:
                toxicity_label = "LOW"
            
            # Get current order book depth (if available)
            try:
                ob_result = await client.market_data.get_order_book(
                    connector_name=config.connector,
                    trading_pair=pair,
                )
                
                if isinstance(ob_result, dict):
                    bids = ob_result.get("bids", [])
                    asks = ob_result.get("asks", [])
                    
                    bid_depth = sum(float(b[1]) for b in bids[:10]) if bids else 0
                    ask_depth = sum(float(a[1]) for a in asks[:10]) if asks else 0
                    
                    depth_imbalance = abs(bid_depth - ask_depth) / (bid_depth + ask_depth) if (bid_depth + ask_depth) > 0 else 0
                else:
                    depth_imbalance = 0.0
            except Exception as e:
                logger.debug(f"Failed to fetch order book for {pair}: {e}")
                depth_imbalance = 0.0
            
            summary_lines.append(
                f"  {pair}:\n"
                f"    VPIN Score: {vpin_score:.3f} ({toxicity_label})\n"
                f"    Order Book Imbalance: {depth_imbalance:.2f}\n"
                f"    Data Points: {len(trades)} trades"
            )
            
            table_data.append({
                "trading_pair": pair,
                "vpin_score": round(vpin_score, 3),
                "toxicity_label": toxicity_label,
                "order_book_imbalance": round(depth_imbalance, 3),
                "data_points": len(trades),
                "high_toxicity": vpin_score >= config.high_vpin_threshold,
            })
        
        except Exception as exc:
            logger.error(f"Failed to calculate VPIN for {pair}: {exc}")
            continue
    
    if not table_data:
        return "Failed to calculate VPIN for any pairs"
    
    summary = "\n".join(summary_lines)
    
    logger.info(f"vpin_calc: Calculated VPIN for {len(table_data)} pairs")
    
    return RoutineResult(
        text=summary,
        table_data=table_data,
        table_columns=[
            "trading_pair", "vpin_score", "toxicity_label",
            "order_book_imbalance", "data_points", "high_toxicity"
        ],
        sections=[
            {
                "title": "VPIN Analysis",
                "content": summary,
            }
        ],
    )
