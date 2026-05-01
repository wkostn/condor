"""LLM output schemas for structured decision-making by Master Agent.

These schemas define the contract between the Master Agent's LLM reasoning 
(Phase 2: DECIDE) and the execution layer (Phase 4: ACT). The Master Agent 
produces JSON conforming to these schemas, which can be validated and executed 
programmatically.

Based on: The Agentic Trading Platform Technical Reference v4.0, Section 6.2
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ActionType(Enum):
    """Type of action the Master Agent can recommend."""
    
    SPAWN_SPECIALIST = "SPAWN_SPECIALIST"  # Deploy a specialist agent on an opportunity
    ADJUST_POSITION = "ADJUST_POSITION"    # Modify an existing position
    CLOSE_POSITION = "CLOSE_POSITION"      # Close an existing position
    SKIP = "SKIP"                          # No action (document reasoning)


class TierType(Enum):
    """Market cap tier classification."""
    
    CORE = "core"              # BTC, ETH
    GROWTH = "growth"          # Mid-cap altcoins (>$500M mcap)
    SPECULATIVE = "speculative"  # Small-cap (<$100M), RWA
    HIGH_RISK = "high_risk"    # Meme coins, Solana launches


class StrategyType(Enum):
    """Available trading strategies by tier."""
    
    # Core/Growth strategies
    GRIDSTRIKE = "gridstrike"
    COMBO_BOT_LONG = "combo_bot_long"
    COMBO_BOT_SHORT = "combo_bot_short"
    DCA_LONG = "dca_long"
    SHORT_DCA = "short_dca"
    SHORT_GRID = "short_grid"
    
    # Speculative strategies
    MOMENTUM_RIDE = "momentum_ride"
    SMART_DCA = "smart_dca"
    RWA_BASIS = "rwa_basis"
    
    # High-Risk strategies
    MEME_SNIPE = "meme_snipe"
    MEME_GRID = "meme_grid"
    QUICK_DCA = "quick_dca"


class CatalystType(Enum):
    """News catalyst classification."""
    
    FUNDAMENTAL_BULLISH = "fundamental_bullish"
    FUNDAMENTAL_BEARISH = "fundamental_bearish"
    SPECULATIVE_PUMP = "speculative_pump"
    SPECULATIVE_DUMP = "speculative_dump"
    STRUCTURAL_LIQUIDATION = "structural_liquidation"
    STRUCTURAL_SUPPLY = "structural_supply"
    REGULATORY_POSITIVE = "regulatory_positive"
    REGULATORY_NEGATIVE = "regulatory_negative"
    MACRO_RISK_ON = "macro_risk_on"
    MACRO_RISK_OFF = "macro_risk_off"
    MEME_VIRAL = "meme_viral"
    TOKEN_LAUNCH = "token_launch"
    UNKNOWN = "unknown"


class MarketRegime(Enum):
    """Current market regime classification."""
    
    RANGING = "ranging"      # ADX < 25, consolidation
    TRENDING_UP = "trending_up"    # ADX > 30, bullish
    TRENDING_DOWN = "trending_down"  # ADX > 30, bearish
    VOLATILE = "volatile"    # High ATR, VPIN > 0.6
    UNCERTAIN = "uncertain"  # Conflicting signals


@dataclass
class ExecutorConfig:
    """Configuration for Hummingbot V2 executor deployment.
    
    This structure maps to the actual executor creation parameters.
    Different strategies use different executor types and configs.
    """
    
    # Common fields
    executor_type: str  # "grid_executor", "dca_executor", "position_executor", etc.
    connector_name: str = "hyperliquid_perpetual"
    trading_pair: str = ""
    side: str = "BUY"  # "BUY" or "SELL"
    
    # Position sizing
    amount_quote: Optional[float] = None  # USD amount (calculated by risk_calculator)
    leverage: float = 1.0
    
    # Risk management
    stop_loss_pct: Optional[float] = None  # e.g., -5.0 for -5%
    take_profit_pct: Optional[float] = None  # e.g., 8.0 for +8%
    trailing_stop: bool = False
    
    # Grid executor specific
    levels: Optional[int] = None  # Number of grid levels (e.g., 40 for GridStrike)
    grid_type: Optional[str] = None  # "arithmetic" or "geometric"
    start_price: Optional[float] = None  # Lower bound
    end_price: Optional[float] = None  # Upper bound
    grid_spacing_pct: Optional[float] = None  # Spacing between levels
    
    # DCA executor specific
    safety_orders: Optional[int] = None  # Number of DCA safety orders
    price_deviation_pct: Optional[float] = None  # Spacing for safety orders
    dca_triggers_pct: Optional[list[float]] = None  # Manual trigger levels [-3, -6, -10]
    
    # Time limits
    max_runtime_hours: Optional[float] = None  # Maximum runtime before forced exit
    
    # Entry conditions (for delayed entry)
    entry_trigger: Optional[str] = None  # e.g., "rsi_4h < 30"
    
    # Additional parameters as JSON
    extra_params: dict = field(default_factory=dict)


@dataclass
class DeploymentAction:
    """A single deployment action recommended by Master Agent."""
    
    # Action metadata
    action_type: ActionType
    asset: str  # e.g., "LINK"
    trading_pair: str  # e.g., "LINK-USDT"
    tier: TierType
    
    # Catalyst analysis
    catalyst_type: CatalystType
    catalyst_summary: str  # 1-2 sentence human-readable summary
    
    # Strategy selection
    strategy: StrategyType
    confidence: float  # 0.0 to 1.0
    
    # Reasoning
    reasoning: str  # 2-3 sentences explaining the decision
    expected_behavior: str  # "Sustained rally", "Mean reversion", "V-bounce", etc.
    
    # Risk assessment
    risk_level: str  # "low", "medium", "high"
    position_size_modifier: float  # 0.5, 0.75, 1.0 based on confidence
    
    # Executor configuration
    executor_config: Optional[ExecutorConfig] = None
    
    # Technical context (for validation)
    entry_price: Optional[float] = None
    support_level: Optional[float] = None
    resistance_level: Optional[float] = None
    
    # Conditions
    entry_conditions: list[str] = field(default_factory=list)
    exit_conditions: list[str] = field(default_factory=list)


@dataclass
class PortfolioRiskAssessment:
    """Portfolio-level risk metrics after proposed deployments."""
    
    # Current state
    total_capital: float
    deployed_capital: float
    available_capital: float
    
    # Tier breakdown
    core_deployed_pct: float
    growth_deployed_pct: float
    speculative_deployed_pct: float
    high_risk_deployed_pct: float
    
    # Risk metrics
    portfolio_leverage: float  # Aggregate leverage
    max_portfolio_loss: float  # Worst-case scenario loss (sum of all stop-losses)
    correlation_risk: str  # "low", "medium", "high"
    
    # Position counts
    total_positions: int
    within_limits: bool  # Moved before fields with defaults
    
    # Fields with defaults
    positions_by_tier: dict = field(default_factory=dict)
    violated_limits: list[str] = field(default_factory=list)


@dataclass
class MasterAgentDecision:
    """Complete decision output from Master Agent's daily analysis.
    
    This is the top-level structure returned by the Master Agent's DECIDE phase.
    It contains all deployment actions, portfolio assessment, and summary.
    """
    
    # Metadata
    timestamp: str  # ISO format
    session_id: str
    tick_number: int
    
    # Market overview
    total_movers_scanned: int
    market_regime: MarketRegime
    regime_notes: str  # Brief description of current market conditions
    
    # Summary
    summary: str  # 2-3 paragraph summary of the day's analysis
    high_confidence_opportunities: int  # Count of confidence >= 0.7
    medium_confidence_opportunities: int  # Count of 0.5 <= confidence < 0.7
    low_confidence_opportunities: int  # Count of confidence < 0.5
    
    # Fields with defaults
    catalyst_breakdown: dict = field(default_factory=dict)  # catalyst_type -> count
    actions: list[DeploymentAction] = field(default_factory=list)
    portfolio_assessment: Optional[PortfolioRiskAssessment] = None
    notable_patterns: list[str] = field(default_factory=list)


@dataclass
class SpecialistAssignment:
    """Assignment data structure passed from Master to Specialist Agent.
    
    When the Master Agent spawns a Specialist, this structure is provided
    as the initial configuration/context.
    """
    
    # Identity
    specialist_id: str  # Unique ID for this specialist agent
    parent_session_id: str  # Master Agent's session ID
    
    # Assignment details
    asset: str
    trading_pair: str
    tier: TierType
    strategy: StrategyType
    
    # Catalyst context
    catalyst_type: CatalystType
    catalyst_summary: str
    confidence: float
    
    # Executor configuration
    executor_config: ExecutorConfig
    
    # Capital allocation
    allocated_capital: float
    max_loss_allowed: float
    
    # Monitoring params
    monitoring_frequency_sec: int = 300  # 5 minutes default
    review_frequency_ticks: int = 12  # Every hour
    report_to_master_every_n_ticks: int = 12
    
    # Fields with defaults
    entry_conditions: list[str] = field(default_factory=list)
    exit_conditions: list[str] = field(default_factory=list)
    alert_conditions: list[str] = field(default_factory=list)


# Validation utilities

def validate_confidence(confidence: float) -> bool:
    """Validate confidence is in [0.0, 1.0] range."""
    return 0.0 <= confidence <= 1.0


def validate_tier_strategy_match(tier: TierType, strategy: StrategyType) -> bool:
    """Validate that the strategy is appropriate for the tier."""
    
    core_growth_strategies = {
        StrategyType.GRIDSTRIKE,
        StrategyType.COMBO_BOT_LONG,
        StrategyType.COMBO_BOT_SHORT,
        StrategyType.DCA_LONG,
        StrategyType.SHORT_DCA,
        StrategyType.SHORT_GRID,
    }
    
    speculative_strategies = {
        StrategyType.MOMENTUM_RIDE,
        StrategyType.SMART_DCA,
        StrategyType.RWA_BASIS,
    }
    
    high_risk_strategies = {
        StrategyType.MEME_SNIPE,
        StrategyType.MEME_GRID,
        StrategyType.QUICK_DCA,
    }
    
    if tier in (TierType.CORE, TierType.GROWTH):
        return strategy in core_growth_strategies
    elif tier == TierType.SPECULATIVE:
        return strategy in (core_growth_strategies | speculative_strategies)
    elif tier == TierType.HIGH_RISK:
        return strategy in high_risk_strategies
    
    return False


def validate_leverage_by_tier(tier: TierType, leverage: float) -> bool:
    """Validate leverage is within tier limits."""
    
    max_leverage = {
        TierType.CORE: 5.0,
        TierType.GROWTH: 3.0,
        TierType.SPECULATIVE: 2.0,
        TierType.HIGH_RISK: 1.0,
    }
    
    return leverage <= max_leverage.get(tier, 1.0)


# Example usage for Master Agent:
"""
# In Master Agent's DECIDE phase, construct output:

decision = MasterAgentDecision(
    timestamp="2026-04-27T06:00:00Z",
    session_id="master_session_123",
    tick_number=1,
    total_movers_scanned=18,
    market_regime=MarketRegime.RANGING,
    regime_notes="Post-ETF rally consolidation. Most assets ranging ±2%.",
    catalyst_breakdown={
        "fundamental_bullish": 2,
        "structural_liquidation": 1,
        "speculative_pump": 3,
    },
    actions=[
        DeploymentAction(
            action_type=ActionType.SPAWN_SPECIALIST,
            asset="LINK",
            trading_pair="LINK-USDT",
            tier=TierType.GROWTH,
            catalyst_type=CatalystType.FUNDAMENTAL_BULLISH,
            catalyst_summary="Swift partnership announcement for cross-border payments",
            strategy=StrategyType.COMBO_BOT_LONG,
            confidence=0.82,
            reasoning="Confirmed news, strong volume, RSI not overbought. Historical precedent: similar partnerships sustain 2-5 days.",
            expected_behavior="Sustained rally → consolidation",
            risk_level="medium",
            position_size_modifier=1.0,
            executor_config=ExecutorConfig(
                executor_type="grid_executor + dca_executor",
                trading_pair="LINK-USDT",
                side="BUY",
                leverage=2.0,
                stop_loss_pct=-5.0,
                take_profit_pct=8.0,
                levels=20,
                grid_spacing_pct=0.4,
                dca_triggers_pct=[-3, -6, -10],
                max_runtime_hours=48,
            ),
            entry_conditions=["RSI 4H < 65", "Price > $14.50 support"],
            exit_conditions=["TP: +8%", "SL: -5%", "Breaking news (bearish)", "Max 48h"],
        ),
    ],
    portfolio_assessment=PortfolioRiskAssessment(
        total_capital=1000.0,
        deployed_capital=150.0,
        available_capital=850.0,
        core_deployed_pct=0.0,
        growth_deployed_pct=15.0,
        speculative_deployed_pct=0.0,
        high_risk_deployed_pct=0.0,
        portfolio_leverage=1.3,
        max_portfolio_loss=-7.5,
        correlation_risk="low",
        total_positions=1,
        positions_by_tier={"growth": 1},
        within_limits=True,
        violated_limits=[],
    ),
    summary="Analyzed 18 movers. Identified 1 high-confidence opportunity (LINK). Market in post-ETF consolidation. Low correlation risk.",
    high_confidence_opportunities=1,
    medium_confidence_opportunities=2,
    low_confidence_opportunities=4,
    notable_patterns=["Growth tier showing relative strength", "Derivatives neutral (funding near 0)"],
)

# Serialize to JSON for logging or API
import json
from dataclasses import asdict

decision_json = json.dumps(asdict(decision), indent=2)
"""
