"""Example of how the agent should use validate_setup.

This demonstrates the expected flow:
1. Run high_vol_coin_levels to get candidates
2. For each candidate, run validate_setup
3. Act on the first GO signal

Agent should call validate_setup like this:

manage_routines(
    action="run",
    name="validate_setup",
    config={
        "trading_pair": candidate["trading_pair"],
        "connector": "binance_perpetual",
        "bias": candidate["bias"],
        "last_price": candidate["last_price"],
        "pullback_level": candidate["pullback_level"],
        "breakout_level": candidate["breakout_level"],
        "breakdown_level": candidate["breakdown_level"],
        "invalid_long_level": candidate["invalid_long_level"],
        "invalid_short_level": candidate["invalid_short_level"],
        "atr_pct": candidate["atr_pct"],
        "proximity_pct": 1.5,
        "max_stop_pct": 4.0,
    }
)

Expected response structure:
{
    "decision": "GO" | "WAIT" | "SKIP" | "MARGINAL",
    "ready": true | false,
    "reason": "High-quality LONG setup at pullback level",
    "quality_score": 76.0,
    "nearest_level": 86.4939,
    "level_type": "pullback",
    "distance_to_entry_pct": 0.06,
    "required_stop_pct": 0.61,
    "rsi": 65.8,
    "adx": 39.1,
    "trend_direction": "bullish",
    ...
}

Decision logic for agent:
- GO (ready=True): Enter trade immediately
- WAIT: Good setup but not at level yet, hold and watch
- SKIP: Stop too wide or poor quality, try next candidate
- MARGINAL: Borderline, use discretion (treat as WAIT)
"""
