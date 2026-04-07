"""T3: Profit-target quantile regressor (alpha=0.75) on y_mfe_atr."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from train_quantile_head import train_quantile


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = train_quantile(Path(args.data), Path(args.output), "tp")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
