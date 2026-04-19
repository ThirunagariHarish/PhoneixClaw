# Correlation Veto

## Purpose
Veto trades when correlated assets (QQQ, DXY, USD/JPY) conflict with the primary signal direction.

## Category
strategy

## Triggers
- Before executing any directional trade
- When primary signal is long SPY/QQQ but DXY is rallying
- When USD/JPY moves against risk-on/risk-off bias

## Inputs
- primarySignal: LONG | SHORT (string)
- primaryAsset: SPY | QQQ | SPX (string)
- qqqDirection: UP | DOWN | FLAT (string)
- dxyDirection: UP | DOWN | FLAT (string)
- usdjpyDirection: UP | DOWN | FLAT (string)
- conflictThreshold: min bars of conflict (number)

## Outputs
- veto: true | false (boolean)
- reason: explanation when vetoed (string)
- conflictingAssets: list of conflicting assets (array)
- overrideAllowed: whether to allow manual override (boolean)

## Steps
1. Map primary signal to expected correlation: long SPY expects QQQ up, DXY down, USD/JPY down (risk-on)
2. Check QQQ: veto long if QQQ down 3+ bars; veto short if QQQ up 3+ bars
3. Check DXY: veto long if DXY up strongly (risk-off); veto short if DXY down strongly
4. Check USD/JPY: similar to DXY; yen strength = risk-off
5. Emit veto=true when 2+ assets conflict; reason lists conflicts
6. Override allowed only with explicit user confirmation

## Example
```yaml
inputs:
  primarySignal: LONG
  qqqDirection: DOWN
  dxyDirection: UP
  usdjpyDirection: UP
outputs:
  veto: true
  reason: "QQQ down, DXY and USD/JPY up — risk-off regime"
  conflictingAssets: [QQQ, DXY, USDJPY]
  overrideAllowed: true
```

## Notes
- Correlations break during regime shifts; use as filter, not absolute
- Reduce veto strictness in low-vol regimes when correlations weaken
