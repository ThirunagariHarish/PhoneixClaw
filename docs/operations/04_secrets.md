# Secrets Management

How Phoenix stores, rotates, and protects secrets. Read this before deploying to production or rotating any keys.

---

## Secrets inventory

| Secret | Where it lives | Used by | Rotation difficulty |
|---|---|---|---|
| `JWT_SECRET_KEY` | `.env` env var | All API auth (login, agent registration, WS auth) | EASY — invalidates existing JWTs but users just log in again |
| `CREDENTIAL_ENCRYPTION_KEY` (Fernet) | `.env` env var | Encrypts connector credentials at rest in `connectors.credentials_encrypted` | HARD — must decrypt-then-reencrypt every connector row |
| `ANTHROPIC_API_KEY` | `.env` env var | Claude SDK calls from agent_gateway | EASY — generate new in Anthropic console, swap in `.env`, restart |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | `.env` env var | Outbound notifications | EASY |
| `WHATSAPP_VERIFY_TOKEN` | `.env` env var | Webhook verification handshake with Meta | EASY (must reconfigure webhook in Meta console) |
| `BRIDGE_TOKEN` | `.env` env var | Internal: legacy openclaw bridge service auth | EASY |
| Per-connector tokens (Discord, Reddit, Twitter, UW) | `connectors.credentials_encrypted` (Postgres) | Encrypted with Fernet at rest, decrypted at runtime by `shared/crypto/credentials.py` | One per connector — re-add the connector via dashboard |
| Per-agent Robinhood credentials | `connectors.credentials_encrypted` → copied to agent's `config.json` at spawn time | `robinhood_mcp.py::_load_credentials()` | One per Robinhood account — re-add via dashboard |
| Per-agent Phoenix API key | `agents.phoenix_api_key` | Agents authenticate report-back calls | Auto-generated on agent creation |

---

## Where secrets are stored

### Local development
- `.env` file in the repo root (gitignored — verify with `git check-ignore .env`)
- Never commit `.env` — only `.env.example` with placeholder values
- Local Postgres holds encrypted connector credentials

### Production (Coolify)
- Coolify's built-in env var encryption handles `.env` for the `phoenix-api` service
- Set via Coolify UI → service → Environment Variables
- Coolify decrypts at container start and exposes via standard env vars
- Postgres data volume holds encrypted connector credentials

### Audit
- All decryption events should write to `system_logs` with `source='credential_decrypt'`
- (Phase H8 follow-up: enforce this in `shared/crypto/credentials.py::decrypt_credentials`)

---

## Rotating the Fernet key (CREDENTIAL_ENCRYPTION_KEY)

This is the hardest rotation because every encrypted row has to be re-encrypted with the new key.

### Procedure

1. **Generate a new key:**
   ```bash
   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

2. **Set BOTH old and new keys in env:**
   ```bash
   CREDENTIAL_ENCRYPTION_KEY=<new-key>          # Used for new encryptions
   CREDENTIAL_ENCRYPTION_KEY_OLD=<old-key>      # Used for fallback decryption
   ```

3. **Update `shared/crypto/credentials.py`** to try both keys when decrypting:
   ```python
   def _get_fernet_chain():
       keys = [os.environ.get("CREDENTIAL_ENCRYPTION_KEY")]
       old = os.environ.get("CREDENTIAL_ENCRYPTION_KEY_OLD")
       if old:
           keys.append(old)
       return MultiFernet([Fernet(k.encode()) for k in keys if k])
   ```

4. **Run the re-encryption migration script:**
   ```bash
   python3 scripts/reencrypt_credentials.py
   ```
   This script:
   - Iterates every `connectors` row with `credentials_encrypted IS NOT NULL`
   - Decrypts using the chain (old key)
   - Re-encrypts using the new key (which is first in the chain)
   - Updates the row in a single transaction
   - Logs the count of rows re-encrypted to `system_logs`

5. **Remove `CREDENTIAL_ENCRYPTION_KEY_OLD` from env** and restart the API

6. **Verify** by listing connectors in the dashboard — credentials should still decrypt

### What happens if you skip rotation
- The old key in your local `.env` is on your developer machine and may be in your shell history, terminal scrollback, or clipboard
- If your laptop is compromised, the attacker can decrypt every connector token (Discord, Robinhood, etc.)
- Recommended: rotate quarterly, or immediately after any laptop loss / repo exposure

---

## Rotating JWT_SECRET_KEY

Easier — just changes signature verification:

1. Generate a new key:
   ```bash
   openssl rand -hex 32
   ```

2. Set `JWT_SECRET_KEY` in `.env` (or Coolify env vars)

3. Restart the API

4. **Side effect:** all existing user JWTs become invalid; users will be redirected to `/login` on their next request. They can log back in normally.

---

## Anthropic / WhatsApp / external API key rotation

1. Generate new key in the provider's console
2. Update `.env` (or Coolify env)
3. Restart the API
4. The old key keeps working until the provider invalidates it (Anthropic: keys are valid until manually deleted in console)

---

## Detecting secret leaks

### Pre-commit check
We use `pre-commit` with the `detect-private-key` and `detect-secrets` hooks. To install:

```bash
pip install pre-commit
pre-commit install
```

Now every `git commit` will scan for private keys and high-entropy strings.

### History audit
To check for any secret that ever made it into git history:

```bash
git log -p | grep -iE "(api[_-]?key|secret|token|password|fernet)" | head -50
```

If you find anything, use BFG Repo-Cleaner to scrub history:

```bash
bfg --delete-files .env
git push --force
```

⚠️ **Force-pushing to main rewrites history.** Coordinate with anyone else who has the repo cloned.

---

## Coolify-specific notes

Coolify stores env vars encrypted at rest using its own server-side key. When you update an env var via the Coolify UI, it:
1. Encrypts the new value with the Coolify master key
2. Stores in Coolify's internal database
3. On container deploy, decrypts and writes to the container's process env

This means:
- Don't put secrets in `docker-compose.coolify.yml` directly — use Coolify's UI for env vars
- Coolify env vars survive container restarts (not lost on rebuild)
- To rotate: update the value in Coolify UI → trigger a redeploy

---

## Emergency: secret leaked

If a secret is publicly exposed (e.g. accidentally pushed to GitHub):

1. **Revoke immediately** in the provider's console (Anthropic, WhatsApp, etc.)
2. **Generate replacement** and update Coolify env
3. **Audit access logs** in the provider's console to see if the leaked key was used
4. **Force-push history scrub** if it's in git history (BFG)
5. **Rotate the Fernet key** if `CREDENTIAL_ENCRYPTION_KEY` was the leaked secret (see above)
6. **Notify users** if any of their credentials may have been decrypted with the old key

---

## Audit checklist (run quarterly)

- [ ] `git ls-files | grep -iE "\.env$|secret|credentials"` returns only `.example` files
- [ ] `pre-commit run --all-files` passes (no private keys in working tree)
- [ ] `JWT_SECRET_KEY` is at least 32 random characters (not the default)
- [ ] `CREDENTIAL_ENCRYPTION_KEY` was rotated within the last 90 days
- [ ] No production secrets in any developer laptop's `.env` (only Coolify-managed ones)
- [ ] All Anthropic / WhatsApp / external API keys in Coolify, not laptop env files
- [ ] `system_logs` has entries for credential decryption events (audit trail working)
