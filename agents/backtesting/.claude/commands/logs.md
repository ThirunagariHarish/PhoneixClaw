Show recent pipeline activity and output logs.

1. Check if there are any log files in the working directory or output/:
   - Look for `*.log` files
   - Look for any stderr/stdout capture files

2. For each completed pipeline step, show a brief summary by reading the output files:
   - **transform**: Read first few lines of transformed.parquet metadata (row count)
   - **enrich**: Check enriched.parquet for row count and column count
   - **preprocess**: Read preprocessing summary from the numpy array shapes
   - **training**: For each model, read the results JSON and show a one-line summary
   - **evaluate**: Show best_model.json contents
   - **patterns**: Show pattern count from patterns.json

3. Check Phoenix API reporting:
   - Read config.json for the phoenix_api_url
   - Show the last reported progress step and percentage

4. If any step produced an error, highlight it prominently with the error message.

Format as a reverse-chronological activity log (newest first).
