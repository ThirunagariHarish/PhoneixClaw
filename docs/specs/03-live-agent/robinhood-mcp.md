# Spec: Robinhood MCP Server

## Purpose

An MCP (Model Context Protocol) server that wraps the `robin_stocks` Python library, allowing Claude Code agents to execute trades on Robinhood. Each live agent includes this as a tool.

## Why MCP

Claude Code natively supports MCP servers as tool providers. By packaging Robinhood access as an MCP server, the agent can call `place_order`, `get_positions`, etc. as first-class tools without custom integration code.

## MCP Server Definition

```json
{
  "mcpServers": {
    "robinhood": {
      "command": "python",
      "args": ["tools/robinhood_mcp.py"],
      "env": {
        "RH_USERNAME": "${ROBINHOOD_USERNAME}",
        "RH_PASSWORD": "${ROBINHOOD_PASSWORD}",
        "RH_MFA_CODE": "${ROBINHOOD_MFA_CODE}"
      }
    }
  }
}
```

## Tools Exposed

### `robinhood_login`
Authenticate with Robinhood.

### `get_quote`
Get current price for a ticker.
```json
{ "ticker": "SPX" }
→ { "price": 5950.25, "bid": 5950.00, "ask": 5950.50, "volume": 1234567 }
```

### `get_positions`
List all open positions.
```json
→ [{ "ticker": "SPX", "quantity": 2, "avg_cost": 5940.00, "current_price": 5950.25, "pnl": 20.50 }]
```

### `get_options_chain`
Get options chain for a ticker.
```json
{ "ticker": "SPX", "expiry": "2026-04-04", "option_type": "call" }
→ [{ "strike": 5950, "bid": 12.50, "ask": 13.00, "volume": 5000, "oi": 25000, "iv": 0.18 }]
```

### `place_stock_order`
Place a stock order.
```json
{ "ticker": "AAPL", "quantity": 10, "side": "buy", "order_type": "limit", "price": 180.00 }
→ { "order_id": "abc123", "status": "queued" }
```

### `place_option_order`
Place an options order.
```json
{ "ticker": "SPX", "strike": 5950, "expiry": "2026-04-04", "option_type": "call", "quantity": 1, "side": "buy", "order_type": "limit", "price": 12.50 }
→ { "order_id": "def456", "status": "queued" }
```

### `close_position`
Close an existing position.
```json
{ "ticker": "SPX", "quantity": 2, "order_type": "market" }
→ { "order_id": "ghi789", "status": "filled", "fill_price": 5955.00 }
```

### `get_account`
Get account info.
```json
→ { "portfolio_value": 50000.00, "buying_power": 25000.00, "cash": 10000.00 }
```

### `get_order_status`
Check status of an order.
```json
{ "order_id": "abc123" }
→ { "status": "filled", "fill_price": 180.05, "filled_quantity": 10 }
```

## Implementation

```python
# agents/live-template/tools/robinhood_mcp.py

import os
import json
import sys
import robin_stocks.robinhood as rh

# MCP protocol over stdin/stdout
def handle_request(request):
    tool = request['params']['name']
    args = request['params']['arguments']
    
    if tool == 'robinhood_login':
        rh.login(
            os.environ['RH_USERNAME'],
            os.environ['RH_PASSWORD'],
            mfa_code=os.environ.get('RH_MFA_CODE'),
            store_session=True,
        )
        return {'success': True}
    
    elif tool == 'get_quote':
        quote = rh.stocks.get_latest_price(args['ticker'])
        return {'price': float(quote[0])}
    
    elif tool == 'get_positions':
        positions = rh.account.get_open_stock_positions()
        return [format_position(p) for p in positions]
    
    elif tool == 'place_stock_order':
        if args['side'] == 'buy':
            order = rh.orders.order_buy_limit(
                args['ticker'], args['quantity'], args['price']
            )
        else:
            order = rh.orders.order_sell_limit(
                args['ticker'], args['quantity'], args['price']
            )
        return {'order_id': order['id'], 'status': order['state']}
    
    elif tool == 'place_option_order':
        order = rh.orders.order_buy_option_limit(
            'open' if args['side'] == 'buy' else 'close',
            args['ticker'],
            args['quantity'],
            args['price'],
            args['expiry'],
            args['strike'],
            args['option_type'],
        )
        return {'order_id': order['id'], 'status': order['state']}
    
    elif tool == 'close_position':
        order = rh.orders.order_sell_market(args['ticker'], args['quantity'])
        return {'order_id': order['id'], 'status': order['state']}
    
    elif tool == 'get_account':
        profile = rh.profiles.load_portfolio_profile()
        return {
            'portfolio_value': float(profile['equity']),
            'buying_power': float(rh.profiles.load_account_profile()['buying_power']),
        }
    
    elif tool == 'get_order_status':
        order = rh.orders.get_stock_order_info(args['order_id'])
        return {'status': order['state'], 'fill_price': order.get('average_price')}

# MCP stdin/stdout loop
for line in sys.stdin:
    request = json.loads(line)
    result = handle_request(request)
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}))
    sys.stdout.flush()
```

## Safety Measures

- **Paper mode**: Config flag to simulate orders without real execution
- **Max order size**: Hard limit on single order value (configurable)
- **Daily loss limit**: Halt trading if daily P&L drops below threshold
- **Rate limiting**: Max 1 order per 30 seconds to avoid rapid-fire
- **Logging**: Every order attempt logged with full context

## Authentication

`robin_stocks` supports TOTP-based 2FA. The agent config stores:
- `robinhood_username` — encrypted
- `robinhood_password` — encrypted  
- `robinhood_totp_secret` — encrypted (for auto-generating MFA codes)

```python
import pyotp
totp = pyotp.TOTP(config['robinhood_totp_secret'])
mfa_code = totp.now()
rh.login(username, password, mfa_code=mfa_code)
```

## Files to Create

| File | Action |
|------|--------|
| `agents/live-template/tools/robinhood_mcp.py` | New — MCP server |
| `agents/live-template/tools/robinhood_paper.py` | New — paper trading simulator |

---

## JSON-RPC 2.0 Protocol Compliance

The MCP server must implement proper JSON-RPC 2.0 with these methods:

### `initialize`
Client sends capabilities; server responds with name, version, supported features.

```json
// Request
{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}}}

// Response
{"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "robinhood-mcp", "version": "1.0.0"}, "capabilities": {"tools": {}}}}
```

### `notifications/initialized`
Client confirms initialization. No response needed.

### `tools/list`
Returns all available tools with JSON Schema input definitions.

### `tools/call`
Executes a tool and returns content array.

```json
// Request
{"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "place_order_with_stop_loss", "arguments": {"ticker": "SPY", "quantity": 10, "side": "buy", "price": 450.00, "stop_loss_pct": 0.05}}}

// Response
{"jsonrpc": "2.0", "id": 5, "result": {"content": [{"type": "text", "text": "{\"main_order_id\": \"abc\", \"stop_order_id\": \"def\", \"status\": \"queued\"}"}]}}
```

### Error Responses

```json
{"jsonrpc": "2.0", "id": 5, "error": {"code": -32000, "message": "Order rejected: insufficient buying power"}}
```

Error codes: -32700 (parse), -32600 (invalid request), -32601 (method not found), -32000 (broker error), -32001 (rate limited), -32002 (auth required).

---

## New Tools

### `place_order_with_stop_loss`
Atomic operation: places main order + protective stop loss in a single call.

```json
{
    "ticker": "SPY",
    "quantity": 10,
    "side": "buy",
    "price": 450.00,
    "order_type": "limit",
    "stop_loss_pct": 0.05,
    "stop_loss_type": "trailing_stop"
}
```
Returns: `{"main_order_id": "...", "stop_order_id": "...", "status": "queued"}`

Implementation:
1. Place main order (limit or market)
2. Wait for fill confirmation (poll every 2s, timeout 60s)
3. Once filled, place stop-loss order at `fill_price * (1 - stop_loss_pct)`
4. Return both order IDs

### `cancel_and_close`
Cancels existing stop-loss order and market-sells the entire position.

```json
{
    "ticker": "SPY",
    "stop_order_id": "def456"
}
```
Steps:
1. Cancel the stop-loss order via `rh.orders.cancel_stock_order(stop_order_id)`
2. Get current position quantity
3. Place market sell for full quantity
4. Return close order confirmation

### `modify_stop_loss`
Adjusts an existing stop-loss order (e.g., tighten trail as profit grows).

```json
{
    "stop_order_id": "def456",
    "ticker": "SPY",
    "new_stop_price": 445.00
}
```
Steps:
1. Cancel existing stop order
2. Place new stop order at `new_stop_price`
3. Return new stop order ID

### `place_order_with_buffer`
For latency-tolerant execution: adjusts limit price by buffer percentage to account for price movement between signal detection and order placement.

```json
{
    "ticker": "SPY",
    "quantity": 10,
    "side": "buy",
    "estimated_price": 450.00,
    "buffer_pct": 0.005,
    "stop_loss_pct": 0.05
}
```
Effective limit price = `estimated_price * (1 + buffer_pct)` for buys, `* (1 - buffer_pct)` for sells.

### `get_option_chain`
Fetch full options chain for a ticker and expiry.

```json
{"ticker": "SPY", "expiry": "2026-04-10", "option_type": "call"}
```
Returns array of contracts with strike, bid, ask, volume, OI, IV.

### `monitor_order`
Polls order status until filled or cancelled (background).

```json
{"order_id": "abc123", "timeout_seconds": 120}
```
Returns final order state with fill price and filled quantity.

---

## Order Fill Monitoring

After placing an order, the MCP server runs a background poll loop:

```python
async def _monitor_fill(self, order_id: str, timeout: int = 120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = rh.orders.get_stock_order_info(order_id)
        if status['state'] in ('filled', 'cancelled', 'rejected'):
            return status
        await asyncio.sleep(2)
    return {"state": "timeout", "order_id": order_id}
```

---

## Rate Limiting

- Max 1 order per 5 seconds (configurable)
- Queue additional orders; process sequentially
- Rate limit state stored in memory with timestamp of last order

```python
class RateLimiter:
    def __init__(self, min_interval: float = 5.0):
        self.min_interval = min_interval
        self.last_order_time = 0.0

    async def acquire(self):
        now = time.time()
        wait = self.min_interval - (now - self.last_order_time)
        if wait > 0:
            await asyncio.sleep(wait)
        self.last_order_time = time.time()
```

---

## Paper Trading Mode

When `config.json` has `"paper_mode": true`:
- All order functions return simulated fills
- Market orders fill at last price + random slippage (0.01% to 0.1%)
- Limit orders fill if last price crosses the limit
- Virtual portfolio tracked in `paper_portfolio.json`
- Identical API surface — agent code doesn't change

---

## Position Reconciliation

On startup and every 5 minutes, reconcile local position state with Robinhood:

```python
def reconcile_positions(local_state: dict, broker_positions: list):
    for bp in broker_positions:
        ticker = bp['ticker']
        if ticker not in local_state:
            log.warning(f"Unknown position {ticker} found in broker — adding to local state")
            local_state[ticker] = bp
        elif abs(local_state[ticker]['quantity'] - bp['quantity']) > 0.01:
            log.warning(f"Quantity mismatch for {ticker}: local={local_state[ticker]['quantity']} broker={bp['quantity']}")
            local_state[ticker]['quantity'] = bp['quantity']
```

---

## Updated Files to Create

| File | Action |
|------|--------|
| `agents/live-template/tools/robinhood_mcp.py` | Rewrite — full MCP JSON-RPC 2.0 server |
| `agents/live-template/tools/robinhood_paper.py` | New — paper trading simulator |
