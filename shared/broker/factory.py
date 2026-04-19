from shared.broker.adapter import BrokerAdapter
from shared.broker.alpaca_adapter import AlpacaBrokerAdapter
from shared.broker.ibkr_adapter import IBKRBrokerAdapter
from shared.broker.robinhood_adapter import RobinhoodBrokerAdapter
from shared.crypto.credentials import decrypt_credentials

BROKER_ADAPTERS = {
    "alpaca": AlpacaBrokerAdapter,
    "robinhood": RobinhoodBrokerAdapter,
    "ibkr": IBKRBrokerAdapter,
}

def create_broker_adapter(broker_type: str, credentials_encrypted: bytes, paper_mode: bool = True) -> BrokerAdapter:
    creds = decrypt_credentials(credentials_encrypted)
    adapter_class = BROKER_ADAPTERS.get(broker_type.lower())
    if not adapter_class:
        raise ValueError(f"Unsupported broker type: {broker_type}")
    if broker_type.lower() == "alpaca":
        secret = creds.get("secret_key") or creds.get("api_secret") or creds.get("secret")
        if not secret:
            raise ValueError("Missing secret_key/api_secret in credentials")
        return adapter_class(api_key=creds["api_key"], secret_key=secret, paper=paper_mode)
    elif broker_type.lower() == "robinhood":
        # Robinhood adapter uses shared MCP server, credentials handled server-side
        mcp_url = creds.get("mcp_url", "http://robinhood-mcp-server:8080")
        return adapter_class(mcp_url=mcp_url)
    elif broker_type.lower() == "ibkr":
        # IBKR via IB Gateway
        host = creds.get("host", "ib-gateway")
        port = creds.get("port", 4001) if paper_mode else creds.get("port", 4000)
        account_id = creds.get("paper_account_id") if paper_mode else creds.get("account_id")
        return adapter_class(host=host, port=port, account_id=account_id)
    return adapter_class(**creds)
