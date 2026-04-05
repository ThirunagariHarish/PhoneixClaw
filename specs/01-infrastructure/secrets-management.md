# Spec: Secrets Management

## Purpose

Unified strategy for managing sensitive credentials across the Phoenix Claw platform: API keys, SSH keys, Discord tokens, Robinhood credentials, and encryption keys.

## Current State

Currently inconsistent:

- **SSH keys**: encrypted with Fernet in DB (via `agent_gateway.py`)
- **Discord tokens**: plaintext in `config.json` on VPS
- **Robinhood credentials**: environment variables on VPS
- **JWT secret**: environment variable
- **DB password**: environment variable

## Target Architecture

All secrets encrypted at rest, with a unified approach.

### Encryption Layers

1. **At-rest encryption**: All secrets in Postgres encrypted with Fernet before storage
2. **In-transit**: HTTPS (Traefik TLS) for API, SSH for VPS communication
3. **In-memory**: Secrets decrypted only when needed, zeroed after use
4. **On VPS**: Secrets injected into agent `.env` files, not in `config.json`

### Fernet Key Management

```python
# shared/crypto/credentials.py

from cryptography.fernet import Fernet
import os

FERNET_KEY = os.environ.get("FERNET_KEY")
if not FERNET_KEY:
    raise RuntimeError("FERNET_KEY environment variable is required")

_fernet = Fernet(FERNET_KEY.encode())


def encrypt_value(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()


def encrypt_credentials(creds: dict) -> str:
    import json
    return encrypt_value(json.dumps(creds))


def decrypt_credentials(encrypted: str) -> dict:
    import json
    return json.loads(decrypt_value(encrypted))
```

### Master Key Location

- **Local dev**: `FERNET_KEY` in `.env` file
- **Production**: Coolify Environment Variables (encrypted by Coolify)
- **Agent VPS**: injected at agent creation time into agent's `.env`
- **Key rotation**: generate new key, re-encrypt all DB values, update `.env` files

## Secret Categories

| Secret | Storage | Encryption | Injection Method |
|--------|---------|------------|------------------|
| `JWT_SECRET_KEY` | Coolify env | Coolify encrypted | Environment variable |
| `DATABASE_URL` | Coolify env | Coolify encrypted | Environment variable |
| `FERNET_KEY` | Coolify env | Coolify encrypted | Environment variable |
| SSH private keys | Postgres | Fernet encrypted | Decrypted in-memory for SSH sessions |
| Discord bot token | Postgres | Fernet encrypted | SCP to agent `.env` on VPS |
| Robinhood username | Postgres | Fernet encrypted | SCP to agent `.env` on VPS |
| Robinhood password | Postgres | Fernet encrypted | SCP to agent `.env` on VPS |
| Robinhood TOTP | Postgres | Fernet encrypted | SCP to agent `.env` on VPS |
| Agent API keys | Postgres | Fernet encrypted | SCP to agent `config.json` on VPS |

**Convention**: Most VPS-bound secrets use `.env`; agent API keys use `config.json` because the agent runtime reads them there (see API Key Lifecycle).

## Per-VPS Secret Injection

When shipping an agent to VPS, the gateway:

1. Retrieves encrypted credentials from DB
2. Decrypts in-memory
3. Creates a temporary `.env` file
4. SCPs the `.env` to the agent directory on VPS
5. Sets file permissions to `600` (owner-only)
6. Clears in-memory copy

```python
async def inject_secrets(ssh_conn, agent_dir: str, secrets: dict):
    env_content = "\n".join(f"{k}={v}" for k, v in secrets.items())
    # Write to temp file, SCP, then delete temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
        f.write(env_content)
        temp_path = f.name
    try:
        await asyncssh.scp(temp_path, (ssh_conn, f"{agent_dir}/.env"))
        await ssh_conn.run(f"chmod 600 {agent_dir}/.env")
    finally:
        os.unlink(temp_path)
```

**Note**: The sample uses `asyncssh.scp` illustratively; the implementation should match the project's actual SSH client (`asyncssh`, Paramiko, or pooled connections from `ssh_pool.py`).

## API Key Lifecycle

### Creation

- Generated during agent creation: `secrets.token_urlsafe(32)`
- Stored encrypted in DB (agent record)
- Injected into agent's `config.json` on VPS

### Rotation

- Manual: `POST /api/v2/agents/{id}/rotate-key`
- Generates new key, encrypts, stores in DB
- SSHs to VPS and updates `config.json`
- Old key invalid immediately

### Revocation

- `DELETE /api/v2/agents/{id}/api-key`
- Agent can no longer call back to Phoenix API
- Used when decommissioning an agent

## Dashboard Rules

- **Never** display full secrets in the UI
- Show masked previews: e.g. `RH_USERNAME: v****d@example.com`
- **SSH keys**: show fingerprint only
- Allow copy-to-clipboard only after re-authentication

## Operational Considerations

### Logging and errors

- Do not log plaintext secrets, decrypted payloads, or full tokens
- Error messages should not echo credential values

### Backups

- Database backups contain Fernet-encrypted blobs; protect backup storage comparably to production DB access
- Rotating `FERNET_KEY` without re-encrypting existing rows renders old ciphertext unreadable; rotation must be a scripted, ordered migration

### Access control

- Only services that provision agents or serve authenticated admin flows should decrypt VPS-bound secrets
- API routes that return agent metadata must use masked fields by default

## Files to Create

| File | Action |
|------|--------|
| `shared/crypto/credentials.py` | New — Fernet encrypt/decrypt utilities |
| `shared/crypto/__init__.py` | New — package init |

## Migration Path (High Level)

1. Add `shared/crypto/credentials.py` and wire `FERNET_KEY` in all environments
2. Migrate Discord and Robinhood fields from plaintext or ad-hoc storage into Fernet-encrypted columns
3. Update agent gateway provisioning to inject `.env` on VPS and retire plaintext secrets in `config.json` where replaced by env vars
4. Add dashboard masking and optional re-auth for sensitive actions
5. Implement rotate/revoke API key endpoints if not already present
