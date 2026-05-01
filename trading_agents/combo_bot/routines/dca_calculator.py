"""DCA Calculator Routine for Combo Bot.

Calculates DCA trigger levels, notional sizes, and mini-grid sell levels
for the Combo Bot strategy.

Given an entry price and DCA configuration, computes:
1. DCA trigger prices (progressive steps below entry)
2. DCA notional sizes (with multiplier scaling)
3. Mini-grid sell levels within each DCA band
4. Total capital required for full DCA deployment

Example usage:
    config = Config(
        entry_price=95000.0,
        base_order_notional=80.0,
        n_dca_orders=5,
        dca_step_pct=0.05,
        dca_multiplier=1.5,
        n_minigrid_levels=5
    )
    
    result = await run(config, context)
    
    # Returns:
    # {
    #   "base_order": {
    #       "price": 95000.0,
    #       "notional": 80.0,
    #       "minigrid_sells": [95950, 96900, 97850, 98800, 99750]
    #   },
    #   "dca_orders": [
    #       {
    #           "slot": 1,
    #           "trigger_price": 90250.0,
    #           "notional": 120.0,
    #           "minigrid_sells": [91153, 92056, 92958, 93861, 94764]
    #       },
    #       ...
    #   ],
    #   "total_capital_required": 1662.50
    # }
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class Config(BaseModel):
    """Configuration for DCA calculator."""
    
    # Entry parameters
    entry_price: float = Field(
        default=95000.0,
        description="Entry price (current market price when deal starts)"
    )
    base_order_notional: float = Field(
        default=80.0,
        description="Base order notional in USD"
    )
    
    # DCA ladder structure
    n_dca_orders: int = Field(
        default=5,
        description="Number of DCA orders below entry"
    )
    dca_step_pct: float = Field(
        default=0.05,
        description="Price drop between each DCA order (as decimal, 0.05 = 5%)"
    )
    dca_multiplier: float = Field(
        default=1.5,
        description="Size scaling multiplier for each DCA order"
    )
    
    # Mini-grid configuration
    n_minigrid_levels: int = Field(
        default=5,
        description="Number of grid sell levels within each DCA band"
    )
    
    # Precision
    price_precision: int = Field(
        default=2,
        description="Price decimal places for rounding"
    )


class RoutineResult(BaseModel):
    """Standard routine result format."""
    text: str
    table_data: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []


def _calculate_minigrid_sells(
    entry_price: float,
    step_pct: float,
    n_levels: int,
    precision: int
) -> list[float]:
    """Calculate evenly-spaced grid sell levels within a DCA band.
    
    For a band spanning [entry, entry*(1+step)], place N sell orders
    at equal intervals.
    
    Args:
        entry_price: Band entry price
        step_pct: Band height as percentage (0.05 = 5%)
        n_levels: Number of grid levels
        precision: Decimal places for rounding
        
    Returns:
        List of sell prices from low to high
    """
    band_top = entry_price * (1 + step_pct)
    level_spacing = (band_top - entry_price) / n_levels
    
    sell_levels = []
    for i in range(1, n_levels + 1):
        sell_price = entry_price + (level_spacing * i)
        sell_levels.append(round(sell_price, precision))
    
    return sell_levels


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    """Calculate DCA levels and mini-grid parameters.
    
    Args:
        config: DCA calculator configuration
        context: Telegram context (unused but required by Condor)
        
    Returns:
        RoutineResult with DCA structure or error string
    """
    try:
        # Calculate base order mini-grid
        base_minigrid_sells = _calculate_minigrid_sells(
            entry_price=config.entry_price,
            step_pct=config.dca_step_pct,
            n_levels=config.n_minigrid_levels,
            precision=config.price_precision
        )
        
        base_order = {
            "price": round(config.entry_price, config.price_precision),
            "notional": round(config.base_order_notional, 2),
            "minigrid_sells": base_minigrid_sells
        }
        
        # Calculate DCA orders
        dca_orders = []
        total_capital = config.base_order_notional
        current_notional = config.base_order_notional
        
        for i in range(1, config.n_dca_orders + 1):
            # DCA trigger price: entry * (1 - step)^i
            trigger_price = config.entry_price * ((1 - config.dca_step_pct) ** i)
            trigger_price = round(trigger_price, config.price_precision)
            
            # DCA notional: base * multiplier^i
            current_notional = current_notional * config.dca_multiplier
            dca_notional = round(current_notional, 2)
            
            # Mini-grid for this DCA band
            dca_minigrid_sells = _calculate_minigrid_sells(
                entry_price=trigger_price,
                step_pct=config.dca_step_pct,
                n_levels=config.n_minigrid_levels,
                precision=config.price_precision
            )
            
            dca_orders.append({
                "slot": i,
                "trigger_price": trigger_price,
                "notional": dca_notional,
                "minigrid_sells": dca_minigrid_sells
            })
            
            total_capital += dca_notional
        
        total_capital = round(total_capital, 2)
        
        # Format response
        text_lines = [
            f"**DCA Calculator Result**",
            f"",
            f"Entry Price: ${config.entry_price:,.2f}",
            f"",
            f"**Base Order:**",
            f"  • Notional: ${base_order['notional']:.2f}",
            f"  • Mini-grid sells: {len(base_minigrid_sells)} levels from ${base_minigrid_sells[0]:,.2f} to ${base_minigrid_sells[-1]:,.2f}",
            f"",
            f"**DCA Ladder ({config.n_dca_orders} levels):**"
        ]
        
        for dca in dca_orders:
            price_drop_pct = (1 - dca['trigger_price'] / config.entry_price) * 100
            text_lines.append(
                f"  • DCA{dca['slot']}: ${dca['trigger_price']:,.2f} (-{price_drop_pct:.1f}%) | "
                f"${dca['notional']:.2f} | "
                f"{len(dca['minigrid_sells'])} grid levels"
            )
        
        text_lines.extend([
            f"",
            f"**Total Capital Required:** ${total_capital:,.2f}",
            f"",
            f"**Mini-Grid Configuration:**",
            f"  • Levels per band: {config.n_minigrid_levels}",
            f"  • Band height: {config.dca_step_pct * 100:.1f}%",
            f"  • Level spacing: {(config.dca_step_pct / config.n_minigrid_levels) * 100:.2f}%"
        ])
        
        text = "\n".join(text_lines)
        
        # Table data for logging
        table_data = [
            {
                "entry_price": config.entry_price,
                "base_notional": base_order["notional"],
                "n_dca_orders": config.n_dca_orders,
                "total_capital": total_capital,
                "dca_deepest_trigger": dca_orders[-1]["trigger_price"],
                "max_drawdown_pct": round((1 - dca_orders[-1]["trigger_price"] / config.entry_price) * 100, 2)
            }
        ]
        
        # Sections for detailed logging
        sections = [
            {
                "title": "base_order",
                "content": str(base_order)
            },
            {
                "title": "dca_orders",
                "content": str(dca_orders)
            },
            {
                "title": "summary",
                "content": f"Total capital: ${total_capital:.2f}, "
                          f"Max drawdown: {table_data[0]['max_drawdown_pct']}%"
            }
        ]
        
        return RoutineResult(
            text=text,
            table_data=table_data,
            sections=sections
        )
        
    except Exception as e:
        logger.error(f"DCA calculator error: {e}", exc_info=True)
        return f"Error calculating DCA parameters: {e}"
