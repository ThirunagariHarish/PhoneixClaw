"""Pre-trade risk validation."""

import argparse
import json
from pathlib import Path


def check_risk(signal: dict, prediction: dict, portfolio: dict, config: dict) -> dict:
    risk = config.get("risk_params", {})

    checks = {
        "confidence_ok": prediction.get("confidence", 0) >= risk.get("confidence_threshold", 0.65),
        "max_positions_ok": portfolio.get("open_positions", 0) < risk.get("max_concurrent_positions", 3),
        "daily_loss_ok": portfolio.get("daily_pnl_pct", 0) > -risk.get("max_daily_loss_pct", 3.0),
        "pattern_match_ok": (
            prediction.get("pattern_matches", 0) >= risk.get("min_pattern_matches", 1)
            if risk.get("require_pattern_match", False)
            else True
        ),
    }

    approved = all(checks.values())
    rejection = next((k for k, v in checks.items() if not v), None)

    return {
        "approved": approved,
        "checks": checks,
        "rejection_reason": rejection,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal", required=True)
    parser.add_argument("--prediction", default="prediction.json")
    parser.add_argument("--portfolio", default="portfolio.json")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--output", default="risk_result.json")
    args = parser.parse_args()

    with open(args.signal) as f:
        signal = json.load(f)
    with open(args.prediction) as f:
        prediction = json.load(f)

    portfolio_path = Path(args.portfolio)
    portfolio = json.loads(portfolio_path.read_text()) if portfolio_path.exists() else {"open_positions": 0, "daily_pnl_pct": 0}

    with open(args.config) as f:
        config = json.load(f)

    result = check_risk(signal, prediction, portfolio, config)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    status = "APPROVED" if result["approved"] else f"REJECTED ({result['rejection_reason']})"
    print(f"Risk check: {status}")


if __name__ == "__main__":
    main()
