"""Risk calculator routine - computes optimal position size based on account equity and risk parameters."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field
from telegram.ext import ContextTypes

from config_manager import get_client
from routines.base import RoutineResult

logger = logging.getLogger(__name__)


class Config(BaseModel):
    """Risk calculator configuration."""
    
    account_equity: float = Field(default=100.0, description="Total account equity in USD")
    risk_per_trade_pct: float = Field(default=2.0, description="Max % of equity to risk per trade (1-5)")
    stop_loss_pct: float = Field(default=2.0, description="Stop loss distance as % (0.5-10)")
    leverage: int = Field(default=5, description="Leverage multiplier (1-50)")
    entry_price: float = Field(default=0.0, description="Planned entry price")
    min_position_usd: float = Field(default=10.0, description="Minimum position size in USD")
    max_position_usd: float = Field(default=500.0, description="Maximum position size in USD")


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    """
    Calculate optimal position size based on risk parameters.
    
    Returns:
        dict with:
        - position_size_usd: Recommended position size in USD (notional)
        - position_size_quote: Amount to allocate from account equity
        - quantity: Asset quantity to buy (position_size_usd / entry_price)
        - risk_amount: Max loss in USD if stop hit
        - risk_pct: Actual risk as % of equity
        - recommendation: "SAFE" / "AGGRESSIVE" / "EXCESSIVE"
    """
    
    # Calculate risk amount (max loss in USD)
    risk_amount = (config.account_equity * config.risk_per_trade_pct) / 100
    
    # Calculate position size (notional with leverage)
    # Formula: risk_amount / (stop_loss_pct / 100) = position needed to hit risk target
    position_size_usd = (risk_amount / (config.stop_loss_pct / 100))
    
    # Account equity needed for this position (before leverage)
    position_size_quote = position_size_usd / config.leverage
    
    # Apply limits
    position_size_usd = max(config.min_position_usd, min(position_size_usd, config.max_position_usd))
    position_size_quote = max(config.min_position_usd, min(position_size_quote, config.account_equity))
    
    # Recalculate based on limits
    actual_risk_amount = position_size_usd * (config.stop_loss_pct / 100)
    actual_risk_pct = (actual_risk_amount / config.account_equity) * 100
    
    # Calculate quantity if entry price provided
    quantity = 0.0
    if config.entry_price > 0:
        quantity = position_size_usd / config.entry_price
    
    # Risk assessment
    if actual_risk_pct <= 2.0:
        recommendation = "SAFE"
    elif actual_risk_pct <= 3.5:
        recommendation = "AGGRESSIVE"
    else:
        recommendation = "EXCESSIVE"
    
    result = {
        "position_size_usd": round(position_size_usd, 2),
        "position_size_quote": round(position_size_quote, 2),
        "quantity": round(quantity, 6) if quantity > 0 else 0.0,
        "risk_amount": round(actual_risk_amount, 2),
        "risk_pct": round(actual_risk_pct, 3),
        "recommendation": recommendation,
        "leverage_used": config.leverage,
        "stop_loss_pct": config.stop_loss_pct,
    }
    
    summary = (
        f"Risk Calculator:\n"
        f"• Position size: ${result['position_size_usd']} notional (${result['position_size_quote']} equity @ {config.leverage}x)\n"
        f"• Risk: ${result['risk_amount']} ({result['risk_pct']:.2f}% of equity)\n"
        f"• Recommendation: {result['recommendation']}\n"
    )
    
    if quantity > 0:
        summary += f"• Quantity: {result['quantity']:.6f} units @ ${config.entry_price}\n"
    
    logger.info(f"Risk calc: equity=${config.account_equity}, risk={actual_risk_pct:.2f}%, size=${position_size_usd}")
    
    return RoutineResult(
        text=summary,
        table_data=[result],
        table_columns=list(result.keys()),
    )
