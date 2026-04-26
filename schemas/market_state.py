"""Market state data structures for Layer 1 → Layer 2 contract.

This module defines the schema that connects the Intelligence Layer (deterministic 
routines) with the Decision Engine (LLM reasoning). All routines should produce data 
conforming to these structures.

Based on: The Agentic Trading Platform Technical Reference v4.0, Section 5.4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class NewsDigest:
    """A single news item from any source."""
    
    headline: str
    source: str  # "cointelegraph", "coinmarketcap", "x_twitter", "coingecko", etc.
    full_text: str  # Raw article/post text for LLM interpretation
    timestamp: datetime
    url: Optional[str] = None
    sentiment_score: Optional[float] = None  # -1.0 to +1.0 if pre-computed


@dataclass
class TechnicalIndicators:
    """Technical analysis indicators computed by tech_overlay routine."""
    
    # Momentum
    rsi_4h: float  # 0-100
    rsi_1d: float  # 0-100
    
    # Trend
    adx: float  # 0-100 (>25 = trending, >50 = strong trend)
    trend_direction: str  # "bullish" | "bearish" | "neutral"
    
    # Volatility
    bollinger_position: float  # -1 to +1 (-1=lower band, +1=upper band, 0=middle)
    atr_percent: float  # ATR as % of price
    
    # Structure
    support_levels: list[float] = field(default_factory=list)  # 3 nearest support
    resistance_levels: list[float] = field(default_factory=list)  # 3 nearest resistance
    
    # Moving averages
    ema_20: Optional[float] = None
    ema_50: Optional[float] = None
    ema_200: Optional[float] = None


@dataclass
class MarketState:
    """Complete market state for a single asset.
    
    This is the contract between Layer 1 (Routines) and Layer 2 (LLM Decision Engine).
    Every routine contributes specific fields to build the complete picture.
    
    Routines that populate fields:
    - morning_scan: Basic price/volume/tier data
    - tech_overlay: Technical indicators
    - news_reader: News digests
    - sentiment_tracker: Sentiment metrics
    - funding_monitor: Derivatives data
    - vpin_calc: Order flow toxicity
    - onchain_intel: On-chain metrics (Speculative/High-Risk only)
    - meme_scanner: Meme-specific data (High-Risk only)
    - rwa_monitor: RWA-specific data (Speculative only)
    """
    
    # Meta
    timestamp: datetime
    asset: str  # Base asset symbol (BTC, ETH, etc.)
    trading_pair: str  # Full pair (BTC-USDT, ETH-USDT, etc.)
    market_cap_tier: str  # "core", "growth", "speculative", "high_risk"
    market_cap: float  # USD market cap
    
    # Price & Volume (from morning_scan)
    price: float
    price_change_24h: float  # Percentage
    volume_24h: float  # USD
    volume_change_24h: float  # Percentage
    
    # Technical Analysis (from tech_overlay routine)
    technical: Optional[TechnicalIndicators] = None
    
    # News & Sentiment (from news_reader + sentiment_tracker)
    news_digests: list[NewsDigest] = field(default_factory=list)
    sentiment_score: Optional[float] = None  # -1.0 to +1.0
    divergence_index: Optional[float] = None  # 0 to 1.0 (price/sentiment mismatch)
    social_volume_anomaly: Optional[bool] = None  # Unusual social activity
    
    # Derivatives (from funding_monitor routine)
    funding_rate: Optional[float] = None
    open_interest_change_24h: Optional[float] = None
    long_short_ratio: Optional[float] = None
    liquidation_clusters: list[dict] = field(default_factory=list)
    
    # Microstructure (from vpin_calc routine)
    vpin: Optional[float] = None  # 0-1 (>0.7 = toxic flow)
    order_book_depth: Optional[float] = None  # USD depth at 1% from mid
    bid_ask_spread: Optional[float] = None  # Percentage
    
    # On-Chain (from onchain_intel - Speculative + High-Risk tiers)
    whale_activity: Optional[dict] = None
    holder_concentration: Optional[float] = None  # Top 10 holders %
    exchange_inflow_anomaly: Optional[bool] = None
    
    # Meme-Specific (from meme_scanner - High-Risk tier only)
    scam_risk_score: Optional[float] = None  # 0-1 (>0.5 = high risk)
    bonding_curve_fill_rate: Optional[str] = None  # "fast", "slow", "organic"
    mint_authority_revoked: Optional[bool] = None
    insider_holding_pct: Optional[float] = None
    token_age_hours: Optional[float] = None
    
    # RWA-Specific (from rwa_monitor - Speculative tier, RWA assets only)
    nav_deviation_pct: Optional[float] = None  # Deviation from NAV
    yield_spread_vs_defi: Optional[float] = None  # Basis points
    proof_of_reserve_status: Optional[str] = None  # "verified", "stale", "failed"
    
    # Portfolio Context (from tier_allocator routine)
    tier_budget_remaining_pct: Optional[float] = None  # % of tier budget available
    
    # Opportunity Scoring (computed by morning_scan)
    opportunity_score: float = 0.0  # 0 to 1.0 (higher = better opportunity)
    
    def is_core_tier(self) -> bool:
        """Check if asset is in Core tier (BTC, ETH)."""
        return self.market_cap_tier == "core"
    
    def is_growth_tier(self) -> bool:
        """Check if asset is in Growth tier (mid-cap altcoins)."""
        return self.market_cap_tier == "growth"
    
    def is_speculative_tier(self) -> bool:
        """Check if asset is in Speculative tier (small-cap, RWA)."""
        return self.market_cap_tier == "speculative"
    
    def is_high_risk_tier(self) -> bool:
        """Check if asset is in High-Risk tier (meme coins, launches)."""
        return self.market_cap_tier == "high_risk"
    
    def has_technical_analysis(self) -> bool:
        """Check if technical analysis is available."""
        return self.technical is not None
    
    def has_news(self) -> bool:
        """Check if news data is available."""
        return len(self.news_digests) > 0
    
    def is_trending(self) -> bool:
        """Check if asset is in a trending market (ADX > 25)."""
        return self.technical is not None and self.technical.adx > 25
    
    def is_toxic_flow(self) -> bool:
        """Check if order flow is toxic (VPIN > 0.7)."""
        return self.vpin is not None and self.vpin > 0.7
    
    def get_summary(self) -> str:
        """Generate a human-readable summary for logging/display."""
        return (
            f"{self.trading_pair} [{self.market_cap_tier.upper()}] "
            f"${self.price:.4f} ({self.price_change_24h:+.2f}%) "
            f"Vol: ${self.volume_24h/1_000_000:.1f}M "
            f"Score: {self.opportunity_score:.2f}"
        )
