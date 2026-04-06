Display the current agent configuration.

1. Read `config.json` and display all settings in organized sections:

   **Identity:**
   - agent_id, channel_name, analyst_name
   - Template version

   **Risk Parameters:**
   - max_position_size, max_portfolio_exposure
   - max_daily_loss, max_concurrent_positions
   - stop_loss_pct, take_profit_pct
   - Any additional risk_params

   **Trading Modes:**
   - List all available modes (aggressive, conservative, scalp, swing, etc.)
   - Highlight currently active mode

   **Intelligence Rules:**
   - List all rules from the manifest with their weights and conditions

   **Model Info:**
   - Best model name and metrics
   - Model artifact paths
   - Feature count used

   **Connections:**
   - Phoenix API URL (mask the API key, show first 8 chars only)
   - Discord channel/server IDs
   - Robinhood connection status (configured yes/no, mask credentials)

   **Knowledge Base:**
   - List any knowledge items from the manifest

2. Read `manifest.json` if it exists for additional structured data.

3. Flag any missing or empty required configuration fields.
