"""Evaluate all trained models and select the best one."""

import argparse
import json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    models_dir = Path(args.models_dir)
    results = []

    for result_file in models_dir.glob("*_results.json"):
        with open(result_file) as f:
            results.append(json.load(f))

    if not results:
        print("No model results found!")
        return

    # Weighted scoring
    for r in results:
        r["score"] = (
            0.30 * r.get("auc_roc", 0.5)
            + 0.30 * min(r.get("profit_factor", 1.0) / 3.0, 1.0)
            + 0.20 * min(r.get("sharpe_ratio", 0.0) / 2.0, 1.0)
            + 0.20 * max(1.0 + r.get("max_drawdown_pct", -50) / 100.0, 0.0)
        )

    results.sort(key=lambda r: r["score"], reverse=True)
    best = results[0]

    output = {
        "best_model": best["model_name"],
        "best_score": best["score"],
        "best_artifact": best.get("artifact_path", ""),
        "all_results": results,
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Best model: {best['model_name']} (score: {best['score']:.4f})")
    for r in results:
        print(f"  {r['model_name']}: score={r['score']:.4f} auc={r.get('auc_roc', 0):.4f} pf={r.get('profit_factor', 0):.2f}")


if __name__ == "__main__":
    main()
