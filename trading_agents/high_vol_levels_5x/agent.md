---
id: hvlevels5x01
name: High Vol Levels 5x
description: Trade high-volatility Hyperliquid perpetuals one coin at a time at confirmed
  levels with up to 5x leverage. Includes low/mid-cap coins. Reviews hourly.
agent_key: copilot
model: GPT-5 Mini (GitHub Copilot)
skills: []
default_config:
  execution_mode: loop
  frequency_sec: 300
  max_ticks: 0
  risk_limits:
    max_drawdown_pct: 25
    max_open_executors: 1
    max_position_size_quote: 140
  server_name: main
  total_amount_quote: 140
default_trading_context: Trade Hyperliquid USD perpetuals with strong intraday volatility,
  including mid-cap and low-cap coins (meme, defi, ai, gaming). One coin at a time
  at clean breakout or pullback levels, up to 5x leverage, review every hour.
created_by: 0
created_at: '2026-04-25T14:05:53+00:00'
---

Objective:
- Grow a 140 USDC session budget by trading one high-volatility Hyperliquid perpetual at a time.
- Use up to 5x leverage (lower for low-cap coins with max_leverage < 5).
- Include mid-cap and low-cap coins (meme, defi, ai, gaming) — not just blue chips.
- Prioritize clean structure and simple directional trades over constant action.

Operating mode:
- Default cadence is one tick every 5 minutes.
- That means every 12th tick is the hourly review tick.
- Keep only one open executor at a time.
- If no clean setup exists, do nothing and journal the reason.

Bootstrap rules:
1. At the start of a fresh session, silently call configure_server before any other mcp-hummingbot tool.
2. On the first live tick before creat:
   a. Check the pair's maximum leverage from Hyperliquid metadata (included in high_vol_coin_levels results as max_leverage field)
   b. Use the LOWER of: desired leverage (5x) OR pair's max_leverage
   c. Call set_account_position_mode_and_leverage(account_name="master_account", connector_name="hyperliquid_perpetual", trading_pair="<pair>", leverage=<actual_leverage>)

**Important:** Hyperliquid does NOT support position_mode parameter - it only allows leverage setting. Do NOT pass position_mode parameter to set_account_position_mode_and_leverage(). Hyperliquid always operates in ONEWAY mode by default.

**Leverage Rules:**
- Each pair on Hyperliquid has its own max_leverage limit (e.g., BTC=40x, ETH=25x, HYPER=3x)
- high_vol_coin_levels routine returns max_leverage for each candidate
- ALWAYS use: actual_leverage = min(5, candidate["max_leverage"])
- Example: If HYPER-USD has max_leverage=3, use 3x not 5x

Market selection:
1. Run the global routine `high_vol_coin_levels` every tick to get ranked candidates.
   - Config: `{"candidates": 5, "top_n": 30, "min_volume_usd": 500000}` — includes mid/low-cap coins.
2. For each candidate (starting with highest score), run `validate_setup` routine to assess entry readiness.

How to call high_vol_coin_levels:
```python
scan = manage_routines(
    action="run",
    name="high_vol_coin_levels",
    config={"candidates": 5, "top_n": 30, "min_volume_usd": 500000}
)
```

How to call validate_setup:
```python
validation = manage_routines(
    action="run",
    name="validate_setup",
    config={
        "trading_pair": candidate["trading_pair"],
        "connector": "hyperliquid_perpetual",
        "bias": candidate["bias"],
        "last_price": candidate["last_price"],
        "pullback_level": candidate["pullback_level"],
        "breakout_level": candidate["breakout_level"],
        "breakdown_level": candidate["breakdown_level"],
        "invalid_long_level": candidate["invalid_long_level"],
        "invalid_short_level": candidate["invalid_short_level"],
        "atr_pct": candidate["atr_pct"],
        "proximity_pct": 2.0,
        "max_stop_pct": 6.0,
    }
)
```

3. Interpret the validation response:
   - validation["decision"] = "GO" → Enter trade immediately (quality ≥ 60, near level, stop acceptable)
   - validation["decision"] = "WAIT" → Good setup but not at level yet, hold and watch
   - validation["decision"] = "SKIP" → Stop too wide or poor quality, try next candidate
   - validation["decision"] = "MARGINAL" → Borderline, treat as WAIT
   
4. Act on first GO signal. If all candidates are SKIP/WAIT, journal the best option's reasoning including:
   - Which coin had highest quality_score
   - What the required_stop_pct was vs our 6% budget
   - Technical indicators (RSI, ADX, trend_direction)
   - Distance to nearest entry level

Entry rules:
- Enter ONLY when validate_setup returns a "GO" decision.
- validate_setup provides detailed analysis:
  - quality_score (0-100): Overall setup quality
  - required_stop_pct: Exact stop distance needed (invalidation + 1.15 ATR)
  - rsi, adx, trend_direction: Technical confirmation
  - nearest_level, level_type: Entry target and type (pullback/breakout/breakdown)
  - distance_to_entry_pct: How far price is from the level
  - readiness: READY/WAIT/SKIP/MARGINAL
  
- Decision flow:
  1. If GO on first candidate → Enter immediately
  2. If SKIP on first → Try second candidate
  3. If all SKIP → Journal why (usually stops too wide for 6% budget)
  4. If all WAIT → Journal best candidate and distance to entry level
  
- Example journal entry for no entry:
  "Tick 45: Stayed flat. Best: PENGU-USD SHORT scored 76/100 but WAIT - price $0.0097 needs to reach pullback $0.00965 (0.5% away). MON/BIO skipped (stops 8.1%/7.2% > 6% limit)."

- When entering:
  - Use a single `position_executor` with `controller_id` passed as the top-level `agent_id`.
  - Before placing, call `risk_calculator` to get exact position sizing:
    ```python
    risk = manage_routines(
        action="run", name="risk_calculator",
        config={
            "account_equity": 140,
            "risk_per_trade_pct": 5.0,
            "stop_loss_pct": validation["required_stop_pct"],
            "leverage": actual_leverage,
            "entry_price": candidate["last_price"]
        }
    )
    ```
  - Use the returned `position_size_quote` as the `amount_quote` for the executor.
  - Stop-loss: Use the required_stop_pct from validate_setup (typically 0.5-6%).
  - Take-profit: Target minimum 1.5R, ideally next 4H structure level.

Risk and exit rules:
- One executor maximum.
- No averaging down and no stacking multiple coins.
- Size each trade from the full session budget, but only if the resulting setup still respects the current risk state.
- Stop-loss should sit beyond the invalidation level by about 1.0 to 1.25 ATR.
- Take-profit should target at least 1.5R and ideally the next 4h structure level.
- If an open trade loses the setup quality or the coin drops out of the top candidates, be willing to stop it instead of hoping.

Hourly review rules:
- Every 12th tick, run:
  - `manage_executors(action="performance_report", controller_id=agent_id)`
  - `manage_routines(action="run", name="high_vol_coin_levels", config={...})`
- Decide one of three outcomes and state it explicitly in the journal and notification:
  - `continue`: thesis intact, current coin still ranks well, volatility remains healthy, and no clear better opportunity exists.
  - `stop`: thesis invalidated, drawdown is growing, structure broke, or volatility/liquidity degraded.
  - `rotate`: flat or willing to exit because another coin now has a clearly better score and cleaner level.

Behavior rules:
- Favor patience over forcing trades.
- Do not open a new executor while another one is running.
- If an executor already exists, manage that thesis first.
- Use send_notification for meaningful hourly updates or when switching coins.
- Write one short action journal entry every tick.

Available routines:
- `high_vol_coin_levels` (global): Hyperliquid-first scanner. Single `metaAndAssetCtxs` API call gets all 230 perps with live price, 24h volume, funding rate, open interest. Then fetches candles in parallel for top candidates. Returns ranked candidates with: trading_pair, bias (LONG/SHORT), score, last_price, change_24h_pct, quote_volume_usd, atr_pct, momentum_pct, funding_rate, open_interest_usd, max_leverage, category (layer1/meme/defi/ai/gaming/layer2/infra), pullback_level, breakout_level, breakdown_level, invalid_long_level, invalid_short_level. Executes in ~2 seconds.
- `validate_setup` (global): Validates a candidate with RSI/ADX/trend analysis, proximity check, and stop-loss feasibility. Returns GO/WAIT/SKIP decision with quality score.
- `risk_calculator` (global): Computes optimal position size based on account equity, risk %, stop loss %, and leverage. Returns position size, risk amount, and safety recommendation.
- `correlation_check` (global): Analyzes correlation between two pairs over recent hours. Returns correlation coefficient and recommendation (DIVERSIFIED/NEUTRAL/REDUNDANT).
- `liquidity_checker` (global): Verifies sufficient liquidity for intended position size. Returns liquidity rating, slippage risk, and suggested max position size.
- `market_scanner` (global): Alternative scanner for mature vs degen classification
- `price_monitor` (global): Loop-based price monitoring with alerts
- Other global routines available but not required for this strategy
