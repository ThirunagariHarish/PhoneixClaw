# Phoenix Trade Bot — k3s Deployment Runbook

This is the canonical operational guide for the production Phoenix deployment. If a new session needs to understand the system or fix something, read this first.

Last verified: 2026-05-04 against commits `a8b4c85` (asyncpg fix), `262eb0e` (db-migrate hook), `f901501` (requirements.txt patches).

---

## 1. Quick orientation

| Where | What |
|---|---|
| **Public URL** | `https://cashflowus.com/` (also `www.cashflowus.com`) |
| **Health check** | `https://cashflowus.com/health` (returns JSON with DB / Redis / scheduler / ingestion / disk) |
| **VPS** | Hostinger KVM, `srv1349789` / `69.62.86.166`, Ubuntu 24.04, 15 GiB RAM, 193 GB disk |
| **Cluster** | k3s v1.30.0, single node. Other tenants on the same cluster: `selfagentbot` (`mission.cashflowus.com`), `argocd`, `monitoring`, `logging`, `cert-manager`, `traefik` |
| **Phoenix namespace** | `phoenix` |
| **Helm release** | `phoenix` (chart at `helm/phoenix/`, current revision visible via `helm list -n phoenix`) |
| **Repo** | `https://github.com/ThirunagariHarish/PhoneixClaw.git` (private; the typo is in the actual repo name) |
| **Image registry** | `ghcr.io/thirunagariharish/phoneixclaw/phoenix-<svc>:<tag>` (cd.yml pushes here on `v*` tags). Local k3s containerd also has `phoenix/phoenix-<svc>:local` from the bootstrap build. |
| **Cluster DNS** | `cashflowus.com` and `www.cashflowus.com` A-record to `69.62.86.166`. cert-manager handles TLS via Let's Encrypt http-01. |

---

## 2. Connect to the cluster

```bash
# From your Mac
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166

# Once on the VPS, kubectl is preconfigured for k3s
kubectl get nodes
kubectl get pods -n phoenix
```

`coolify_deploy` is the historical key name; despite the name it's the only working SSH key on the VPS today.

---

## 3. What's running in the `phoenix` namespace

15 app services + 3 infra + edge:

| Pod | Type | Port | Notes |
|---|---|---|---|
| `phoenix-api` | Deployment | 8011 | FastAPI; **single replica** (in-memory `_running_tasks` dict). 2Gi memory limit. |
| `phoenix-dashboard` | Deployment | 80 | React SPA (nginx-served) |
| `edge-nginx` | Deployment | 80 | Public reverse proxy. Routes `/api/`, `/auth/`, `/ws/`, `/health`, `/assets/`, `/` to the right backends. ConfigMap-mounted nginx.conf. |
| `phoenix-ws-gateway` | Deployment | 8031 | WebSocket fan-out |
| `phoenix-llm-gateway` | Deployment | 8050 | Ollama → falls back to Anthropic via `ANTHROPIC_API_KEY` |
| `phoenix-broker-gateway` | Deployment | 8040 | Robinhood/IB broker. **Has a 100Mi PVC at `/app/data/.tokens`** to persist Robinhood MFA session tokens. |
| `phoenix-execution` | Deployment | 8020 | Order executor |
| `phoenix-automation` | Deployment | — | **Worker, no HTTP, no Service, no probes** |
| `phoenix-discord-ingestion` | Deployment | 8060 | Discord channel listener |
| `phoenix-feature-pipeline` | Deployment | 8055 | Feature enrichment |
| `phoenix-inference-service` | Deployment | 8045 | ML inference |
| `phoenix-agent-orchestrator` | Deployment | 8070 | Agent runtime |
| `phoenix-prediction-monitor` | Deployment | 8075 | Live prediction tracker |
| `phoenix-backtesting` | Deployment | 8085 | Backtest runner |
| `postgres` | StatefulSet | 5432 | TimescaleDB pg16, 10Gi PVC. User `phoenixtrader`, db `phoenixtrader`. |
| `redis` | Deployment | 6379 | redis:7-alpine, 256Mi maxmemory |
| `minio` | StatefulSet | 9000/9001 | MinIO S3-compatible, 5Gi PVC |

Secrets: `phoenix-secrets` (k8s `Secret` decrypted from `phoenix-secrets` `SealedSecret` in the same namespace). 6 keys: `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`, `ANTHROPIC_API_KEY`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`.

ConfigMap: `phoenix-config` (non-secret env). Annotated as Helm `pre-install,pre-upgrade` hook with weight `-10` so it exists before app pods start.

Edge config: `edge-nginx-config` ConfigMap mounts nginx.conf into the edge pod.

Ingress: k8s `Ingress` (class `traefik`) with `cert-manager.io/cluster-issuer: letsencrypt-prod` annotation. cert-manager auto-creates the `phoenix-tls` Certificate.

---

## 4. Common operations

### 4.1 See what's healthy

```bash
# Pods
kubectl get pods -n phoenix
kubectl top pods -n phoenix

# Public health (most useful one-liner)
curl -fsS https://cashflowus.com/health | jq

# Helm release state
helm list -n phoenix
helm history phoenix -n phoenix
```

### 4.2 Tail a service log

```bash
kubectl logs -n phoenix deploy/phoenix-api --tail=100 -f
kubectl logs -n phoenix -l app.kubernetes.io/component=phoenix-broker-gateway --tail=100 -f
```

### 4.3 Restart a service after a code/config change

```bash
kubectl rollout restart deployment/phoenix-api -n phoenix
kubectl rollout status deployment/phoenix-api -n phoenix
```

### 4.4 Exec into a pod

```bash
kubectl exec -it -n phoenix deploy/phoenix-api -- bash
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader
```

### 4.5 Port-forward for local debugging

```bash
kubectl port-forward -n phoenix svc/phoenix-api 8011:8011
# now hit http://localhost:8011/health
```

---

## 5. Build + deploy a new image (the routine path)

Two flows: **CI** (tag-based, normal) and **VPS-local** (bootstrap or hotfix).

### 5.1 CI flow (normal — once GitHub Actions secrets are in place)

```bash
git tag v1.0.1
git push origin v1.0.1
# .github/workflows/cd.yml builds 14 images, pushes to ghcr.io,
# SCPs the chart, runs `helm upgrade --install ... --set image.tag=v1.0.1`
```

Required GitHub secrets at https://github.com/ThirunagariHarish/PhoneixClaw/settings/secrets/actions:
- `K3S_HOST` = `69.62.86.166`
- `K3S_SSH_KEY` = the contents of `~/.ssh/coolify_deploy`

### 5.2 VPS-local flow (bootstrap or when CI is broken)

```bash
# On your Mac: package + ship source
tar --exclude=node_modules --exclude=.venv --exclude=.git --exclude=.pytest_cache \
    --exclude=.mypy_cache --exclude=.ruff_cache --exclude=.playwright-mcp \
    --exclude=audit -czf /tmp/phoenix-src.tar.gz .
scp -i ~/.ssh/coolify_deploy /tmp/phoenix-src.tar.gz root@69.62.86.166:/tmp/
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 "rm -rf /opt/phoenix && mkdir -p /opt/phoenix && tar -xzf /tmp/phoenix-src.tar.gz -C /opt/phoenix"

# On the VPS: build + import to k3s containerd
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166
cd /opt/phoenix
for entry in \
  "phoenix-api:apps/api/Dockerfile" \
  "phoenix-dashboard:apps/dashboard/Dockerfile" \
  "phoenix-ws-gateway:services/ws-gateway/Dockerfile" \
  "phoenix-llm-gateway:services/llm-gateway/Dockerfile" \
  "phoenix-broker-gateway:services/broker-gateway/Dockerfile" \
  "phoenix-execution:services/execution/Dockerfile" \
  "phoenix-automation:services/automation/Dockerfile" \
  "phoenix-discord-ingestion:services/discord-ingestion/Dockerfile" \
  "phoenix-feature-pipeline:services/feature-pipeline/Dockerfile" \
  "phoenix-inference-service:services/inference-service/Dockerfile" \
  "phoenix-agent-orchestrator:services/agent-orchestrator/Dockerfile" \
  "phoenix-prediction-monitor:services/prediction-monitor/Dockerfile" \
  "phoenix-backtesting:services/backtesting/Dockerfile" \
  "phoenix-nginx:infra/Dockerfile.nginx"; do
  IFS=":" read -r svc dockerfile <<< "$entry"
  docker build -q -t "phoenix/$svc:local" -f "$dockerfile" . && \
    docker save "phoenix/$svc:local" | k3s ctr images import -
done

# Re-deploy with local image overrides
helm upgrade phoenix /opt/phoenix/helm/phoenix \
  -f /opt/phoenix/helm/phoenix/values.prod.yaml -n phoenix \
  --set image.repository=phoenix \
  --set image.tag=local \
  --set image.pullPolicy=IfNotPresent
```

### 5.3 Hotfix one service only

```bash
# After source is on the VPS at /opt/phoenix
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 "
  cd /opt/phoenix && \
  docker build -t phoenix/phoenix-broker-gateway:local -f services/broker-gateway/Dockerfile . && \
  docker save phoenix/phoenix-broker-gateway:local | k3s ctr images import - && \
  kubectl rollout restart deployment/phoenix-broker-gateway -n phoenix
"
```

---

## 6. Traps to know about

These are real ways to break the cluster — I've hit each one.

### 6.1 `helm upgrade` without the local-image overrides will break everything

Until images are pushed to GHCR, `values.prod.yaml`'s `ghcr.io/.../phoenix-X:latest` refs don't resolve. Always pass:

```
--set image.repository=phoenix --set image.tag=local --set image.pullPolicy=IfNotPresent
```

Long-term fix: push images to GHCR and remove the overrides.

### 6.2 `helm uninstall` deletes the SealedSecret

The chart's `sealedsecret.yaml` is helm-owned (it lives in `templates/`). Uninstalling removes both the SealedSecret AND the downstream Secret (controller GCs it). Re-install requires re-applying the SealedSecret first:

```bash
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 "kubectl apply -n phoenix -f -" \
  < helm/phoenix/templates/sealedsecret.yaml

# Then adopt it into helm so the next install/upgrade doesn't conflict:
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 "
  kubectl annotate sealedsecret phoenix-secrets -n phoenix \
    meta.helm.sh/release-name=phoenix \
    meta.helm.sh/release-namespace=phoenix --overwrite && \
  kubectl label sealedsecret phoenix-secrets -n phoenix \
    app.kubernetes.io/managed-by=Helm --overwrite
"
```

### 6.3 Memory pressure can pin pods in `Pending`

The node has 15 GiB. selfagentbot uses ~5.6 GiB. Phoenix's limits sum to ~9.5 GiB. If a rolling update creates new pods that need to coexist briefly with old ones, the new ones may be `0/1 Insufficient memory`. Force-delete the old broken pods to free RAM:

```bash
kubectl get pods -n phoenix --field-selector=status.phase=Pending -o name | \
  xargs -r kubectl delete -n phoenix --grace-period=0 --force
```

Or scale a non-critical deployment temporarily:

```bash
kubectl scale deployment phoenix-backtesting -n phoenix --replicas=0
# do the work, then
kubectl scale deployment phoenix-backtesting -n phoenix --replicas=1
```

### 6.4 db-migrate is a `post-install` hook, not pre-install

Earlier the chart had it as `pre-install`, which crashed because postgres wasn't created yet (`socket.gaierror: Name or service not known`). Current chart runs db-migrate AFTER postgres is up, with an `initContainer` that waits up to 240s for `postgres:5432` to accept connections. Don't move it back to pre-install.

### 6.5 `DATABASE_URL` must use `postgresql+asyncpg://`

The codebase uses `sqlalchemy.ext.asyncio.create_async_engine`. With a plain `postgresql://` URL, sqlalchemy falls back to `psycopg2` which isn't installed in the service images (`ModuleNotFoundError: No module named 'psycopg2'`). Every chart template that constructs DATABASE_URL must include the `+asyncpg` driver suffix.

### 6.6 argocd will fight your install

The chart at `helm/phoenix/argocd-application.yaml` registers Phoenix as an argocd Application with `selfHeal: true` and `valueFiles: [values.prod.yaml]`. If applied, argocd will try to reconcile Phoenix to use ghcr.io images (per values.prod.yaml). Until those images exist in GHCR, argocd's reconciliation breaks the deploy. **Don't apply `argocd-application.yaml` until images are in GHCR**, or the Application has been pointed at a `values.local.yaml` with local image refs.

---

## 7. Bootstrap admin user (first-time-only)

On a fresh database, no users exist. The `users` and `invitations` tables are empty. Phoenix's `/auth/register` endpoint requires an invitation code; without one, it returns `403 Invalid or already-used invitation code`.

Bootstrap path:

```bash
# Generate a one-time bootstrap code
BOOTSTRAP=$(openssl rand -hex 16)

# Inject as env var on phoenix-api
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 "
  kubectl set env deployment/phoenix-api -n phoenix PHOENIX_ADMIN_INVITE_CODE=$BOOTSTRAP && \
  kubectl rollout status deployment/phoenix-api -n phoenix --timeout=2m
"

# Register the first user (becomes admin because invitation_code matches the bootstrap code)
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 "
  kubectl exec -n phoenix deploy/phoenix-api -- curl -fsS -X POST \
    http://localhost:8011/auth/register \
    -H 'Content-Type: application/json' \
    -d '{\"email\":\"<your-email>\",\"password\":\"<your-pw>\",\"invitation_code\":\"$BOOTSTRAP\"}'
"

# Remove the bootstrap env var (one-time use only)
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 "kubectl set env deployment/phoenix-api -n phoenix PHOENIX_ADMIN_INVITE_CODE-"
```

Subsequent users are added via the dashboard's invitation flow (admin → invite).

---

## 8. Connecting Robinhood, Discord, brokers (post-deploy)

Broker credentials and Discord bot tokens are NOT chart-level secrets. They're managed at runtime via the dashboard's **Connectors** panel and stored encrypted (Fernet, using `CREDENTIAL_ENCRYPTION_KEY`) in the `connectors` table.

After login:
1. Go to Connectors → Add → Robinhood (or Discord, IB, etc.)
2. Enter creds; first Robinhood login may trigger a device-approval challenge — open the Robinhood mobile app and tap Approve
3. The session token caches to the broker-gateway's PVC at `/app/data/.tokens` and survives pod restarts

If the broker-gateway pod is recreated and the PVC is intact, sessions persist. If the PVC is deleted, you'll re-trigger MFA on next request.

---

## 9. Disaster recovery

### 9.1 Roll back a bad helm upgrade

```bash
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 "
  helm history phoenix -n phoenix
  helm rollback phoenix <revision-number> -n phoenix --wait
"
```

### 9.2 Postgres data is gone (PVC deleted, etc.)

The `pgdata-postgres-0` PVC stores all Phoenix data. If lost:
- No backup currently configured (TODO).
- The schema is recreated by `phoenix-db-migrate` on next install.
- All users, agents, trades, and positions will be empty — re-bootstrap admin per §7.

### 9.3 SealedSecret can't decrypt (cluster rebuilt)

The Bitnami sealed-secrets controller stores its master key as a Secret in `kube-system`. If k3s is reinstalled, the new controller has a different key and old ciphertexts won't decrypt. You'd need to re-seal each secret:

```bash
# On the new cluster, with kubeseal installed (see helm/phoenix/README.md)
echo -n "<plaintext>" | kubeseal --raw --namespace phoenix --name phoenix-secrets
```

To back up the controller's key (recommended):

```bash
kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key \
  -o yaml > sealed-secrets-key.backup.yaml
# Store this file securely OUTSIDE the cluster.
```

### 9.4 Cluster is gone entirely

1. Re-provision: `infra/scripts/provision-k3s.sh` (k3s + sealed-secrets + cert-manager + Let's Encrypt ClusterIssuer + UFW)
2. Restore the sealed-secrets controller key (§9.3 backup)
3. Re-build and import images per §5.2
4. `helm install phoenix ...` per §5.2

---

## 10. Known issues / future work

| Issue | Severity | Notes |
|---|---|---|
| Images not in GHCR | medium | `cd.yml` will push on next `v*` tag. Until then, any helm upgrade needs `--set image.repository=phoenix --set image.tag=local --set image.pullPolicy=IfNotPresent`. |
| argocd Application not registered | low | Deferred until images are in GHCR (would otherwise break the install — see §6.6). |
| GitHub Actions secrets not set | medium | Add `K3S_HOST` + `K3S_SSH_KEY` at https://github.com/ThirunagariHarish/PhoneixClaw/settings/secrets/actions before the first CD run. |
| No postgres backup | high | Needs a CronJob that runs `pg_dump` to MinIO. Not implemented. |
| sealed-secrets master key not backed up off-cluster | high | If cluster is destroyed, all secrets are unrecoverable. Backup procedure in §9.3. |
| selfagentbot argocd is also broken | low | Same `authentication required` error as Phoenix would get. Both apps need a repo PAT added to argocd. |
| Memory headroom is ~5 GiB | medium | Phoenix limits sum to ~9.5 GiB; selfagentbot uses ~5.6 GiB; node has 15 GiB. Concurrent rolling updates can pin pods Pending. |
| One-replica services (api, broker-gateway, etc.) | accepted | Several services hold in-memory state and can't be horizontally scaled until the state moves to Redis. |
| Dependabot alert #36 (moderate) on the repo | low | Unrelated to this work; review at https://github.com/ThirunagariHarish/PhoneixClaw/security/dependabot/36 |

---

## 11. Useful one-liners

```bash
# What's the public URL doing right now
curl -fsS https://cashflowus.com/health | jq

# Which pods are unhealthy
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 \
  "kubectl get pods -n phoenix --field-selector=status.phase!=Running"

# Recent events (most useful diagnostic)
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 \
  "kubectl get events -n phoenix --sort-by='.lastTimestamp' | tail -30"

# Rolling restart everything (dangerous; respects rolling update strategy)
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 \
  "kubectl rollout restart deployment -n phoenix"

# psql session
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 \
  "kubectl exec -it -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader"

# Verify image pinned in cluster matches latest local build
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 \
  "k3s ctr images list -q | grep phoenix/"

# Memory headroom across the node
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 \
  "kubectl describe node | sed -n '/Allocated resources/,/Events:/p'"
```
