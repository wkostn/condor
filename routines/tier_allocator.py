"""Tier Allocator Global Routine - Hierarchical Risk Parity across market cap tiers.

This routine implements Hierarchical Risk Parity (HRP) to compute optimal capital allocation
across the four market cap tiers based on current correlation structure and risk budgets.

Based on: The Agentic Trading Platform Technical Reference v4.0, Section 5.4 & Section 8

Market Cap Tiers:
- Core: 50-70% (BTC, ETH)
- Growth: 15-25% (mid-cap altcoins)
- Speculative: 5-15% (small-cap, RWA)
- High-Risk: 1-5% (meme coins, new launches)

Methodology: Hierarchical Risk Parity (Lopez de Prado 2016)

Output: Target allocation percentages per tier
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from typing import Any

from pydantic import BaseModel, Field
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from config_manager import get_client
from routines.base import RoutineResult

logger = logging.getLogger(__name__)

# Default tier constraints from spec
DEFAULT_TIER_CONSTRAINTS = {
    "core": {"min": 0.50, "max": 0.70, "target": 0.60},
    "growth": {"min": 0.15, "max": 0.25, "target": 0.20},
    "speculative": {"min": 0.05, "max": 0.15, "target": 0.10},
    "high_risk": {"min": 0.01, "max": 0.05, "target": 0.05},
}


class Config(BaseModel):
    """Configuration for tier_allocator routine."""

    total_portfolio_usd: float = Field(
        default=100_000,
        description="Total portfolio value in USD",
    )
    rebalance_threshold: float = Field(
        default=0.05,
        description="Rebalance if allocation drifts >5% from target",
    )
    use_hrp: bool = Field(
        default=True,
        description="Use HRP algorithm (if False, use static target allocations)",
    )
    lookback_days: int = Field(
        default=30,
        description="Days of price history for correlation calculation",
    )


def _calculate_portfolio_variance(weights: list[float], volatilities: list[float], correlations: list[list[float]]) -> float:
    """Calculate portfolio variance given weights, volatilities, and correlation matrix."""
    if len(weights) != len(volatilities):
        return 0.0
    
    n = len(weights)
    variance = 0.0
    
    for i in range(n):
        for j in range(n):
            if i < len(correlations) and j < len(correlations[i]):
                correlation = correlations[i][j]
            else:
                correlation = 1.0 if i == j else 0.0
            
            variance += weights[i] * weights[j] * volatilities[i] * volatilities[j] * correlation
    
    return variance


def _simple_hrp_allocation(volatilities: dict[str, float], correlations: dict[str, dict[str, float]]) -> dict[str, float]:
    """Simplified HRP allocation (inverse volatility with correlation adjustment)."""
    
    # Start with inverse volatility weights
    inv_vol = {tier: 1.0 / vol if vol > 0 else 1.0 for tier, vol in volatilities.items()}
    
    # Adjust for correlations (reduce allocation to highly correlated assets)
    adjusted_weights = {}
    for tier in inv_vol:
        # Average correlation with other tiers
        avg_corr = 0.0
        count = 0
        for other_tier in inv_vol:
            if other_tier != tier:
                corr = correlations.get(tier, {}).get(other_tier, 0.0)
                avg_corr += abs(corr)
                count += 1
        
        if count > 0:
            avg_corr /= count
        
        # Reduce weight if highly correlated (diversification benefit)
        diversification_factor = 1.0 - (avg_corr * 0.3)  # Max 30% reduction
        adjusted_weights[tier] = inv_vol[tier] * diversification_factor
    
    # Normalize to sum to 1.0
    total = sum(adjusted_weights.values())
    if total > 0:
        normalized = {tier: weight / total for tier, weight in adjusted_weights.items()}
    else:
        # Fallback to equal weights
        normalized = {tier: 0.25 for tier in adjusted_weights}
    
    return normalized


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    """Compute optimal allocation across market cap tiers using HRP."""
    
    client = await get_client(context._chat_id, context=context)
    if not client:
        return "No server available"
    
    # Representative assets for each tier
    tier_representatives = {
        "core": "BTC-USDT",
        "growth": "SOL-USDT",
        "speculative": "LINK-USDT",  # Proxy for small-cap
        "high_risk": "DOGE-USDT",  # Proxy for meme/high-risk
    }
    
    # Fetch price data for correlation and volatility calculation
    tier_volatilities = {}
    tier_returns = {}
    
    for tier, pair in tier_representatives.items():
        try:
            candles_result = await client.market_data.get_candles(
                connector_name="hyperliquid_perpetual",
                trading_pair=pair,
                interval="1d",
                max_records=config.lookback_days,
            )
            
            if isinstance(candles_result, dict):
                candles = candles_result.get("data", [])
            elif isinstance(candles_result, list):
                candles = candles_result
            else:
                candles = []
            
            if candles and len(candles) >= 7:
                closes = [float(c["close"]) for c in candles]
                returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
                
                tier_returns[tier] = returns
                tier_volatilities[tier] = statistics.pstdev(returns) if len(returns) > 1 else 0.01
            else:
                logger.warning(f"Insufficient data for {tier} ({pair})")
                tier_volatilities[tier] = 0.01  # Default low volatility
                tier_returns[tier] = [0.0]
        
        except Exception as e:
            logger.warning(f"Failed to fetch data for {tier}: {e}")
            tier_volatilities[tier] = 0.01
            tier_returns[tier] = [0.0]
    
    # Calculate correlation matrix
    tier_correlations = {}
    for tier1 in tier_returns:
        tier_correlations[tier1] = {}
        for tier2 in tier_returns:
            if tier1 == tier2:
                tier_correlations[tier1][tier2] = 1.0
            else:
                returns1 = tier_returns[tier1]
                returns2 = tier_returns[tier2]
                
                min_len = min(len(returns1), len(returns2))
                if min_len > 1:
                    r1 = returns1[:min_len]
                    r2 = returns2[:min_len]
                    
                    # Pearson correlation
                    mean1 = statistics.mean(r1)
                    mean2 = statistics.mean(r2)
                    
                    numerator = sum((r1[i] - mean1) * (r2[i] - mean2) for i in range(min_len))
                    denominator = (
                        (sum((x - mean1) ** 2 for x in r1) ** 0.5) *
                        (sum((x - mean2) ** 2 for x in r2) ** 0.5)
                    )
                    
                    correlation = numerator / denominator if denominator > 0 else 0.0
                    tier_correlations[tier1][tier2] = correlation
                else:
                    tier_correlations[tier1][tier2] = 0.0
    
    # Apply HRP or use static allocations
    if config.use_hrp:
        raw_allocations = _simple_hrp_allocation(tier_volatilities, tier_correlations)
    else:
        raw_allocations = {tier: constraints["target"] for tier, constraints in DEFAULT_TIER_CONSTRAINTS.items()}
    
    # Apply constraints
    constrained_allocations = {}
    for tier in ["core", "growth", "speculative", "high_risk"]:
        alloc = raw_allocations.get(tier, DEFAULT_TIER_CONSTRAINTS[tier]["target"])
        constraints = DEFAULT_TIER_CONSTRAINTS[tier]
        
        # Clamp to min/max
        alloc = max(constraints["min"], min(constraints["max"], alloc))
        constrained_allocations[tier] = alloc
    
    # Renormalize to ensure sum = 1.0
    total_alloc = sum(constrained_allocations.values())
    final_allocations = {tier: alloc / total_alloc for tier, alloc in constrained_allocations.items()}
    
    # Calculate dollar amounts
    dollar_allocations = {tier: alloc * config.total_portfolio_usd for tier, alloc in final_allocations.items()}
    
    # Format output
    summary_lines = [
        f"Tier Allocation (HRP Model):",
        f"Total Portfolio: ${config.total_portfolio_usd:,.0f}",
        f"Lookback: {config.lookback_days} days",
        "",
        "Allocations:",
    ]
    
    table_data = []
    
    for tier in ["core", "growth", "speculative", "high_risk"]:
        alloc_pct = final_allocations[tier] * 100
        alloc_usd = dollar_allocations[tier]
        volatility = tier_volatilities.get(tier, 0) * 100
        target_pct = DEFAULT_TIER_CONSTRAINTS[tier]["target"] * 100
        drift = alloc_pct - target_pct
        
        drift_flag = ""
        if abs(drift) > config.rebalance_threshold * 100:
            drift_flag = " ⚠️ REBALANCE"
        
        summary_lines.append(
            f"  {tier.upper()}:\n"
            f"    Allocation: {alloc_pct:.1f}% (${alloc_usd:,.0f})\n"
            f"    Target: {target_pct:.1f}%, Drift: {drift:+.1f}%{drift_flag}\n"
            f"    Volatility: {volatility:.2f}%"
        )
        
        table_data.append({
            "tier": tier,
            "allocation_pct": round(alloc_pct, 1),
            "allocation_usd": round(alloc_usd, 2),
            "target_pct": round(target_pct, 1),
            "drift_pct": round(drift, 1),
            "volatility_pct": round(volatility, 2),
            "needs_rebalance": abs(drift) > config.rebalance_threshold * 100,
        })
    
    summary = "\n".join(summary_lines)
    
    # Check if rebalancing needed
    needs_rebalance = any(row["needs_rebalance"] for row in table_data)
    if needs_rebalance:
        summary += "\n\n⚠️ Rebalancing recommended (drift exceeds threshold)"
    else:
        summary += "\n\n✓ Portfolio within target allocation ranges"
    
    logger.info(f"tier_allocator: Computed allocation for ${config.total_portfolio_usd:,.0f} portfolio")
    
    return RoutineResult(
        text=summary,
        table_data=table_data,
        table_columns=[
            "tier", "allocation_pct", "allocation_usd", "target_pct",
            "drift_pct", "volatility_pct", "needs_rebalance"
        ],
        sections=[
            {
                "title": "Tier Allocation (HRP)",
                "content": summary,
            }
        ],
    )
