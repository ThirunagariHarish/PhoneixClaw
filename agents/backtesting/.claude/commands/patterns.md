Display all discovered trading patterns and LLM-generated strategies.

1. Read `output/patterns.json` if it exists.
   - Show each pattern with: name, description, win_rate, sample_size, edge_vs_baseline
   - Sort by edge descending
   - Flag patterns with sample_size < 10 as low-confidence

2. Read `output/llm_patterns.json` if it exists.
   - Show the analyst_profile section
   - For each strategy: name, description, entry_rules, exit_rules, edge_explanation, risk_notes, win_rate, sample_size
   - Show regime_insights and temporal_insights sections
   - Show risk_factors

3. If neither file exists, report that pattern discovery has not run yet and suggest running:
   ```
   python tools/discover_patterns.py --data output/ --output output/patterns.json
   python tools/analyze_patterns_llm.py --data output/ --output output/llm_patterns.json --config config.json
   ```

Format everything clearly with headers and separators for easy reading.
