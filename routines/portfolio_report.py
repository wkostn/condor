"""Portfolio Report Global Routine - Aggregate all active positions.

This routine aggregates P&L, runtime, executor status, and risk metrics across
all active trading agents and their positions. Provides portfolio-level oversight.

Based on: The Agentic Trading Platform Technical Reference v4.0, Section 5.4

Output: Portfolio summary with tier breakdown (Core/Growth/Speculative/High-Risk)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from telegram.ext import ContextTypes

from config_manager import get_client
from routines.base import RoutineResult

logger = logging.getLogger(__name__)


class Config(BaseModel):
    """Configuration for portfolio_report routine."""

    include_closed_positions: bool = Field(
        default=False,
        description="Include recently closed positions in the report",
    )
    lookback_hours: int = Field(
        default=24,
        description="Hours to lookback for closed positions",
    )


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    """Generate portfolio report across all active agents."""
    
    client = await get_client(context._chat_id, context=context)
    if not client:
        return "No server available"
    
    # Fetch active bots
    try:
        bots_result = await client.bot_orchestration.get_all_bots()
        
        if isinstance(bots_result, dict):
            active_bots = bots_result.get("data", [])
        elif isinstance(bots_result, list):
            active_bots = bots_result
        else:
            return f"Unexpected bots data format: {type(bots_result)}"
        
        if not active_bots:
            return "No active trading bots"
        
        logger.info(f"Found {len(active_bots)} active bots")
    
    except Exception as exc:
        logger.error(f"Failed to fetch active bots: {exc}")
        return f"Failed to fetch active bots: {exc}"
    
    # Aggregate data by tier
    tiers = {
        "core": {"bots": [], "total_pnl": 0, "total_positions": 0},
        "growth": {"bots": [], "total_pnl": 0, "total_positions": 0},
        "speculative": {"bots": [], "total_pnl": 0, "total_positions": 0},
        "high_risk": {"bots": [], "total_pnl": 0, "total_positions": 0},
        "unknown": {"bots": [], "total_pnl": 0, "total_positions": 0},
    }
    
    portfolio_total_pnl = 0
    portfolio_total_value = 0
    
    # Process each bot
    for bot in active_bots:
        bot_id = bot.get("id", "unknown")
        bot_name = bot.get("name", "unnamed")
        status = bot.get("status", "unknown")
        config_data = bot.get("config", {})
        
        # Try to determine tier from bot name or config
        tier = "unknown"
        bot_name_lower = bot_name.lower()
        if "btc" in bot_name_lower or "eth" in bot_name_lower:
            tier = "core"
        elif any(x in bot_name_lower for x in ["sol", "avax", "matic", "arb"]):
            tier = "growth"
        elif "meme" in bot_name_lower or "pump" in bot_name_lower:
            tier = "high_risk"
        elif any(x in bot_name_lower for x in ["rwa", "smallcap"]):
            tier = "speculative"
        
        # Try to fetch performance metrics
        try:
            perf_result = await client.bot_orchestration.get_bot_performance(bot_id)
            
            if isinstance(perf_result, dict):
                perf_data = perf_result.get("data", {})
                pnl = float(perf_data.get("total_pnl_usd", 0) or 0)
                position_count = int(perf_data.get("open_positions", 0) or 0)
            else:
                pnl = 0
                position_count = 0
            
            portfolio_total_pnl += pnl
            
            tiers[tier]["bots"].append({
                "id": bot_id,
                "name": bot_name,
                "status": status,
                "pnl_usd": pnl,
                "positions": position_count,
            })
            
            tiers[tier]["total_pnl"] += pnl
            tiers[tier]["total_positions"] += position_count
        
        except Exception as e:
            logger.debug(f"Failed to get performance for bot {bot_id}: {e}")
            
            # Add bot with unknown metrics
            tiers[tier]["bots"].append({
                "id": bot_id,
                "name": bot_name,
                "status": status,
                "pnl_usd": 0,
                "positions": 0,
            })
    
    # Format output
    summary_lines = [
        f"Portfolio Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Active Bots: {len(active_bots)}",
        f"Total P&L: ${portfolio_total_pnl:,.2f}",
        "",
        "Breakdown by Tier:",
    ]
    
    table_data = []
    
    for tier_name, tier_data in tiers.items():
        if not tier_data["bots"]:
            continue
        
        summary_lines.append(
            f"\n  {tier_name.upper()}:\n"
            f"    Bots: {len(tier_data['bots'])}\n"
            f"    Positions: {tier_data['total_positions']}\n"
            f"    P&L: ${tier_data['total_pnl']:,.2f}"
        )
        
        # Add individual bot details
        for bot in tier_data["bots"]:
            summary_lines.append(
                f"      - {bot['name']} ({bot['status']}): "
                f"${bot['pnl_usd']:,.2f}, {bot['positions']} pos"
            )
            
            table_data.append({
                "tier": tier_name,
                "bot_id": bot["id"],
                "bot_name": bot["name"],
                "status": bot["status"],
                "pnl_usd": bot["pnl_usd"],
                "open_positions": bot["positions"],
            })
    
    summary = "\n".join(summary_lines)
    
    logger.info(f"portfolio_report: Generated report for {len(active_bots)} bots, total P&L: ${portfolio_total_pnl:.2f}")
    
    return RoutineResult(
        text=summary,
        table_data=table_data,
        table_columns=["tier", "bot_id", "bot_name", "status", "pnl_usd", "open_positions"],
        sections=[
            {
                "title": "Portfolio Summary",
                "content": summary,
            }
        ],
    )
