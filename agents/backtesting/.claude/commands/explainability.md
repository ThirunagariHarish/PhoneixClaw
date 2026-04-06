Display model explainability results showing which features drive predictions.

1. Read `output/explainability.json` if it exists.
   - Show the model name and method used (SHAP, feature_importance, etc.)
   - Display the top-20 most important features in a ranked table:
     ```
     Rank | Feature Name           | Importance | Category
     -----|------------------------|------------|----------
     1    | rsi_14                 | 0.0842     | Technical
     2    | vix_level              | 0.0731     | Market Context
     3    | sentiment_score        | 0.0654     | Sentiment
     ```

2. If explainability.json does not exist, try to extract feature importance directly:
   - Check if `output/models/xgboost_model.pkl` or similar exists
   - Read the feature names from preprocessing output

3. Group the top features by category and show category-level importance:
   - Technical Indicators: X%
   - Market Context: X%
   - Sentiment: X%
   - Time Features: X%
   - Price Action: X%
   - Volume: X%
   - Options: X%
   - Temporal: X%

4. Highlight any surprising findings (e.g., time features ranking very high, or expected features ranking very low).
