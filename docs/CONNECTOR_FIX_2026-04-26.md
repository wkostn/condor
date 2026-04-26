# Configuration Issue Resolution - April 26, 2026

## Problem Identified

The agent attempted to trade but failed with a perfect setup:
- **ETH-USDT LONG**: 86/100 quality score, 0.92% stop, 0.02% from pullback
- **Error**: "binance_perpetual 5x HEDGE setup failed at the exchange layer"

## Root Cause

**Connector Mismatch:**
- Agent configured to use: `binance_perpetual`
- Hummingbot actually configured with: `hyperliquid_perpetual`
- Agent tried to set leverage on non-existent connector → Failed

### Files Affected:
1. `/trading_agents/high_vol_levels_5x/agent.md` (line 53)
2. `/trading_agents/high_vol_levels_5x/routines/high_vol_coin_levels.py` (line 27)
3. `/routines/validate_setup.py` (line 32)

## Resolution

### Changes Made:

1. **Agent Instructions** (agent.md)
   - Changed `"connector": "binance_perpetual"` → `"connector": "hyperliquid_perpetual"`
   - Updated bootstrap rule #3 to use hyperliquid_perpetual

2. **Agent-Local Routine** (high_vol_coin_levels.py)
   - Changed default connector from `binance_perpetual` → `hyperliquid_perpetual`

3. **Global Routine** (validate_setup.py)
   - Changed default connector from `binance_perpetual` → `hyperliquid_perpetual`

4. **MCP Configuration**
   - Updated strategy instructions via MCP

5. **Docker Sync**
   - All files synced to container

### Files Updated:
✅ agent.md
✅ high_vol_coin_levels.py (agent-local)
✅ validate_setup.py (global)
✅ MCP strategy config

## How Connectors Work

### Data Fetching (Scanning):
- `high_vol_coin_levels` uses Binance public API to scan top coins by volume
- This is fine - doesn't require authentication
- Provides list of liquid, high-vol candidates

### Trading Execution:
- Must use actual configured Hummingbot connector
- In your case: `hyperliquid_perpetual`
- Used for:
  - Setting leverage/position mode
  - Fetching candles for analysis
  - Placing orders

## Configuration Flow

```
Agent Instructions
    ↓
Specify connector: "hyperliquid_perpetual"
    ↓
Pass to validate_setup → Fetches candles from hyperliquid
    ↓
Set leverage on hyperliquid_perpetual → Success ✓
    ↓
Create position_executor on hyperliquid → Trade executes ✓
```

## What Was Blocked

The following setup couldn't execute due to connector mismatch:

| Pair | Bias | Quality | Stop | Distance | Status |
|------|------|---------|------|----------|--------|
| ETH-USDT | LONG | 86/100 | 0.92% | 0.02% | ❌ Blocked by connector |
| ORCA-USDT | LONG | - | 10.62% | - | ❌ Stop too wide |
| ZBT-USDT | SHORT | - | 18.91% | - | ❌ Stop too wide |
| LAB-USDT | LONG | - | 17.88% | - | ❌ Stop too wide |
| RAVE-USDT | LONG | - | 11.13% | - | ❌ Stop too wide |

**ETH was the only tradeable setup** and it failed due to configuration issue!

## Next Steps

1. **Restart the Agent**
   ```
   /stop
   /start hvlevels
   ```
   This will create a fresh session (Session 4) with corrected config.

2. **Monitor First Trade**
   - Should execute on next good setup
   - ETH/SOL/BTC typically have tight stops (0.5-2%)
   - Check journal for validate_setup calls

3. **Verify Connector**
   ```bash
   docker exec hummingbird-condor-1 bash -c "cd /app && grep connector /app/trading_agents/high_vol_levels_5x/agent.md | head -5"
   ```
   Should show: `hyperliquid_perpetual`

## Telegram Configuration (Optional)

Agent mentioned: `TELEGRAM_BOT_TOKEN is not configured`

- **Not required** - MCP notifications work fine (you received this!)
- **Optional** - Allows agent to send direct notifications
- To enable: Set `TELEGRAM_TOKEN` in `/app/.env` (see `.env.example`)

## Lessons Learned

1. **Always match connector to configured exchange**
2. **Test bootstrap rules before live trading** (leverage setup is critical)
3. **Check connector in 3 places:**
   - Agent instructions
   - Agent-local routines
   - Global routines (if used)

## Verification Checklist

Before starting agent:
- [ ] Check agent.md connector → `hyperliquid_perpetual` ✓
- [ ] Check agent-local routine connector → `hyperliquid_perpetual` ✓
- [ ] Check global routine connector default → `hyperliquid_perpetual` ✓
- [ ] Verify Hummingbot has hyperliquid_perpetual configured ✓
- [ ] MCP strategy updated ✓
- [ ] Docker synced ✓

**Status: READY TO TRADE** ✅

---

*Generated: 2026-04-26*
*Session: ead72583-faee-4487-ba35-cf9cd5163967*
