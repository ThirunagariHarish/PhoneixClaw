# Bayesian Updater

## Purpose
Bayesian probability updating for trade signals and regime beliefs.

## Category
advanced-ai

## Triggers
- When updating signal probability with new evidence
- When combining multiple signal sources
- When user requests probability update
- When strategy uses probabilistic thresholds

## Inputs
- `prior`: number — Prior probability (0–1)
- `likelihood`: number — P(evidence | hypothesis)
- `evidence`: number — P(evidence) or normalization
- `observations`: object[] — Multiple observations for sequential update
- `model`: string — "binary", "multi", "beta"

## Outputs
- `posterior`: number — Updated probability
- `belief`: object — Full belief distribution if multi
- `metadata`: object — Prior, likelihood, update count
- `confidence`: number — Belief strength (optional)

## Steps
1. Validate prior in [0, 1]
2. Apply Bayes rule: posterior = prior * likelihood / evidence
3. For sequential: use posterior as next prior
4. For Beta: update alpha, beta from successes/failures
5. Return posterior and metadata
6. Optionally persist for tracking

## Example
```
Input: prior=0.6, likelihood=0.8, evidence=0.7, model="binary"
Output: {
  posterior: 0.686,
  metadata: {prior: 0.6, likelihood: 0.8, evidence: 0.7},
  confidence: 0.72
}
```

## Notes
- Beta prior for binary outcomes (success/failure)
- Multi-class uses Dirichlet
- Useful for combining ML signal with fundamental view
