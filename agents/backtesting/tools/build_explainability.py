"""Build explainability model using SHAP and surrogate decision tree."""

import argparse
import json
from pathlib import Path

import joblib
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="Directory containing best model")
    parser.add_argument("--data", required=True, help="Directory with preprocessed data")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    model_dir = Path(args.model)
    data_dir = Path(args.data)

    with open(data_dir / "meta.json") as f:
        meta = json.load(f)

    feature_names = meta["feature_columns"]
    X_test = np.load(data_dir / "X_test.npy")

    if len(X_test) == 0:
        output = {
            "model_name": "",
            "method": "skipped",
            "top_features": [],
            "error": "X_test is empty",
        }
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        print("Explainability skipped: X_test is empty")
        return

    with open(model_dir / "best_model.json") as f:
        best_info = json.load(f)

    best_name = best_info["best_model"]
    model_path = model_dir / f"{best_name}_model.pkl"

    if not model_path.exists():
        print(f"Model file not found: {model_path}")
        # Fallback: use feature importances from results
        result_path = model_dir / f"{best_name}_results.json"
        if result_path.exists():
            with open(result_path) as f:
                results = json.load(f)
            importances = results.get("feature_importances", {})
        else:
            importances = {}

        output = {
            "model_name": best_name,
            "method": "feature_importances_fallback",
            "top_features": sorted(importances.items(), key=lambda x: x[1], reverse=True)[:30],
        }
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        return

    model = joblib.load(model_path)

    # Try SHAP
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_test[:min(500, len(X_test))])

        if isinstance(shap_values, list):
            shap_values = shap_values[1]

        mean_abs_shap = np.abs(shap_values).mean(axis=0)
        feature_importance = sorted(
            zip(feature_names, mean_abs_shap.tolist()),
            key=lambda x: x[1],
            reverse=True,
        )

        output = {
            "model_name": best_name,
            "method": "shap",
            "top_features": [{"feature": f, "importance": round(v, 6)} for f, v in feature_importance[:30]],
        }
    except Exception as e:
        # Fallback to model feature_importances_ if available
        if hasattr(model, "feature_importances_"):
            importances = model.feature_importances_
            feature_importance = sorted(
                zip(feature_names, importances.tolist()),
                key=lambda x: x[1],
                reverse=True,
            )
            output = {
                "model_name": best_name,
                "method": "feature_importances",
                "top_features": [{"feature": f, "importance": round(v, 6)} for f, v in feature_importance[:30]],
            }
        else:
            output = {
                "model_name": best_name,
                "method": "none",
                "error": str(e),
                "top_features": [],
            }

    # Build surrogate decision tree
    try:
        from sklearn.tree import DecisionTreeClassifier, export_text
        y_pred = model.predict(X_test)
        surrogate = DecisionTreeClassifier(max_depth=5)
        surrogate.fit(X_test, y_pred)
        tree_text = export_text(surrogate, feature_names=feature_names, max_depth=5)
        output["surrogate_tree"] = tree_text
        joblib.dump(surrogate, model_dir / "surrogate_tree.pkl")
    except Exception:
        pass

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Explainability built: {len(output.get('top_features', []))} features ranked")
    for feat in output.get("top_features", [])[:5]:
        print(f"  {feat['feature']}: {feat['importance']:.4f}")


if __name__ == "__main__":
    main()
