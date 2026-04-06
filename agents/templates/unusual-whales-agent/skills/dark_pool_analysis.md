# Dark Pool Analysis Skill

## What Are Dark Pools?
Private exchanges where large institutional orders trade away from public order books. Their prints reveal where smart money is positioning.

## Key Indicators
- **Block trades > 100K shares**: Institutional accumulation
- **Repeat block buyer**: Same ticker hit multiple times in a day
- **Off-market price prints**: Big buyers willing to pay premium
- **Late-day blocks**: Often signals next-day moves

## How to Combine with Options Flow
1. **Bullish confirmation**: Call flow + dark pool buying = strong conviction
2. **Bearish confirmation**: Put flow + dark pool selling = strong conviction
3. **Divergence**: Calls flowing but dark pools selling = avoid (institutions distributing)
4. **Stealth accumulation**: No options flow but consistent dark pool buying = early signal

## Action Rules
- Dark pool block > $5M + matching options flow → take a position
- Dark pool block alone (no options confirmation) → add to watchlist, not trade
- Multiple dark pool blocks at same price level → that level is now support/resistance

## Reporting
Always broadcast significant dark pool prints to other agents via:
```bash
python tools/agent_comms.py --broadcast --intent unusual_flow --data dark_pool.json
```

This helps other agents (especially position monitor sub-agents) factor institutional positioning into their decisions.
