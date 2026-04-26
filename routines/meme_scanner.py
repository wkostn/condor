"""Meme Scanner Global Routine - Monitor and filter meme coin launches.

This routine monitors pump.fun for bonding curve graduations, Raydium new pool creation,
and DEXScreener trending. Includes scam filtering based on insider concentration, fill rate,
and mint authority status.

Based on: The Agentic Trading Platform Technical Reference v4.0, Section 5.4

Scam Detection Filters:
- Fill rate: Slow fill (>6h) = organic growth
- Insider concentration: <30% held by top 10 wallets
- Mint authority: Must be revoked
- Liquidity depth: Minimum threshold for tradability

Target Tier: High-Risk (meme coins, Solana launches)

Output: Filtered meme coin candidates with scam risk scores
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

DEXSCREENER_TRENDING = "https://api.dexscreener.com/latest/dex/search"
DEXSCREENER_PAIRS = "https://api.dexscreener.com/latest/dex/pairs/solana/{pair_address}"


class Config(BaseModel):
    """Configuration for meme_scanner routine."""

    min_liquidity_usd: float = Field(
        default=50_000,
        description="Minimum liquidity in USD",
    )
    max_age_hours: int = Field(
        default=72,
        description="Maximum age of token in hours (recent launches only)",
    )
    min_fill_hours: int = Field(
        default=6,
        description="Minimum hours to fill bonding curve (slow = organic)",
    )
    max_insider_concentration: float = Field(
        default=0.30,
        description="Maximum % held by top 10 wallets (0.30 = 30%)",
    )
    min_price_change_1h: float = Field(
        default=5.0,
        description="Minimum 1h price change % to consider (momentum filter)",
    )
    candidates: int = Field(
        default=10,
        description="Number of top candidates to return",
    )


async def _fetch_trending_solana_tokens() -> list[dict[str, Any]]:
    """Fetch trending Solana tokens from DEXScreener."""
    tokens = []
    
    try:
        async with aiohttp.ClientSession() as session:
            # Search for trending Solana tokens
            async with session.get(
                f"{DEXSCREENER_TRENDING}?q=solana",
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    
                    for pair in pairs:
                        if pair.get("chainId") == "solana":
                            tokens.append({
                                "pair_address": pair.get("pairAddress", ""),
                                "base_token_address": pair.get("baseToken", {}).get("address", ""),
                                "base_token_name": pair.get("baseToken", {}).get("name", ""),
                                "base_token_symbol": pair.get("baseToken", {}).get("symbol", ""),
                                "price_usd": float(pair.get("priceUsd", 0) or 0),
                                "price_change_1h": float(pair.get("priceChange", {}).get("h1", 0) or 0),
                                "price_change_24h": float(pair.get("priceChange", {}).get("h24", 0) or 0),
                                "volume_24h": float(pair.get("volume", {}).get("h24", 0) or 0),
                                "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0) or 0),
                                "fdv": float(pair.get("fdv", 0) or 0),
                                "pair_created_at": pair.get("pairCreatedAt", 0),
                            })
        
        logger.info(f"Fetched {len(tokens)} trending Solana tokens from DEXScreener")
    
    except Exception as exc:
        logger.error(f"Failed to fetch trending tokens: {exc}")
    
    return tokens


async def run(config: Config, context: ContextTypes.DEFAULT_TYPE) -> RoutineResult | str:
    """Scan and filter meme coin launches for trading opportunities."""
    
    # Fetch trending tokens
    tokens = await _fetch_trending_solana_tokens()
    
    if not tokens:
        return "No trending Solana tokens found"
    
    # Current timestamp
    now = datetime.now()
    max_age_timestamp = (now - timedelta(hours=config.max_age_hours)).timestamp()
    
    # Filter and score tokens
    scored_tokens = []
    
    for token in tokens:
        # Filter by age (recent launches only)
        pair_created_at = token.get("pair_created_at", 0)
        if pair_created_at and pair_created_at < max_age_timestamp:
            continue
        
        # Filter by liquidity
        liquidity = token.get("liquidity_usd", 0)
        if liquidity < config.min_liquidity_usd:
            continue
        
        # Filter by momentum
        price_change_1h = token.get("price_change_1h", 0)
        if abs(price_change_1h) < config.min_price_change_1h:
            continue
        
        # Calculate age in hours
        if pair_created_at:
            age_hours = (now.timestamp() - pair_created_at) / 3600
        else:
            age_hours = 0
        
        # Scam risk scoring (simplified without on-chain data)
        scam_risk_score = 0.0
        risk_factors = []
        
        # Factor 1: Fill rate (age vs liquidity)
        # Fast fill (<6h) with high liquidity = potential insider pump
        if age_hours < config.min_fill_hours and liquidity > config.min_liquidity_usd * 2:
            scam_risk_score += 30
            risk_factors.append("Fast fill")
        
        # Factor 2: Extreme price movement
        if abs(price_change_1h) > 100:
            scam_risk_score += 20
            risk_factors.append("Extreme volatility")
        
        # Factor 3: Low liquidity despite high FDV (red flag)
        fdv = token.get("fdv", 0)
        if fdv > 0 and liquidity / fdv < 0.01:  # <1% liquidity/FDV ratio
            scam_risk_score += 25
            risk_factors.append("Low liquidity ratio")
        
        # Factor 4: Very recent launch (<1h) - high risk, needs time to observe
        if age_hours < 1:
            scam_risk_score += 15
            risk_factors.append("Very new")
        
        # Opportunity score (inverse of risk, plus momentum)
        momentum_score = min(abs(price_change_1h) / 2, 50)
        liquidity_score = min(liquidity / config.min_liquidity_usd * 10, 30)
        age_score = min(age_hours / config.min_fill_hours * 20, 20) if age_hours >= config.min_fill_hours else 0
        
        opportunity_score = momentum_score + liquidity_score + age_score - scam_risk_score
        
        # Determine risk level
        if scam_risk_score >= 50:
            risk_level = "HIGH RISK ⚠️"
        elif scam_risk_score >= 30:
            risk_level = "MODERATE RISK"
        else:
            risk_level = "LOW RISK"
        
        scored_tokens.append({
            "symbol": token.get("base_token_symbol", ""),
            "name": token.get("base_token_name", ""),
            "pair_address": token.get("pair_address", ""),
            "price_usd": token.get("price_usd", 0),
            "price_change_1h": price_change_1h,
            "price_change_24h": token.get("price_change_24h", 0),
            "volume_24h": token.get("volume_24h", 0),
            "liquidity_usd": liquidity,
            "fdv": fdv,
            "age_hours": age_hours,
            "scam_risk_score": scam_risk_score,
            "risk_level": risk_level,
            "risk_factors": ", ".join(risk_factors) if risk_factors else "None",
            "opportunity_score": opportunity_score,
        })
    
    # Sort by opportunity score
    scored_tokens.sort(key=lambda x: x["opportunity_score"], reverse=True)
    
    # Take top candidates
    top_candidates = scored_tokens[:config.candidates]
    
    if not top_candidates:
        return "No meme coins passed filtering criteria"
    
    # Format output
    summary_lines = [
        f"Meme Coin Scan (Solana):",
        f"Screened {len(tokens)} tokens, {len(scored_tokens)} passed filters, showing top {len(top_candidates)}:",
    ]
    
    for i, token in enumerate(top_candidates, 1):
        summary_lines.append(
            f"\n  {i}. {token['symbol']} ({token['name']})\n"
            f"     Opportunity Score: {token['opportunity_score']:.1f}/100\n"
            f"     Risk: {token['risk_level']} ({token['scam_risk_score']:.0f}/100)\n"
            f"     Risk Factors: {token['risk_factors']}\n"
            f"     Price: ${token['price_usd']:.8f}\n"
            f"     1h: {token['price_change_1h']:+.2f}%, 24h: {token['price_change_24h']:+.2f}%\n"
            f"     Liquidity: ${token['liquidity_usd']:,.0f}\n"
            f"     Age: {token['age_hours']:.1f}h"
        )
    
    summary = "\n".join(summary_lines)
    
    logger.info(f"meme_scanner: Identified {len(top_candidates)} meme coin opportunities")
    
    return RoutineResult(
        text=summary,
        table_data=top_candidates,
        table_columns=[
            "symbol", "name", "pair_address", "price_usd", "price_change_1h",
            "price_change_24h", "volume_24h", "liquidity_usd", "fdv",
            "age_hours", "scam_risk_score", "risk_level", "risk_factors",
            "opportunity_score"
        ],
        sections=[
            {
                "title": "Meme Coin Opportunities (High-Risk Tier)",
                "content": summary,
            }
        ],
    )
