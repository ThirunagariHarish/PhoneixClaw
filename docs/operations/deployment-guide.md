# Deploying Phoenix to VPS with k3s and Helm

Step-by-step guide to deploy the Phoenix Trade Bot platform on a VPS using k3s and Helm.

---

## Prerequisites

| Requirement | Details |
|---|---|
| VPS | 2+ vCPU, 8 GB RAM, 50 GB storage (KVM or dedicated recommended) |
| Domain name | Point A records to your VPS IP (`cashflowus.com` and `www.cashflowus.com`) |
| SSH access | root or sudo user |
| Git | Repo cloned locally or on VPS |

### Minimum VPS specs

The full stack runs 15 microservices + 3 infrastructure containers (Postgres, Redis, MinIO). Recommended: **8 GB RAM**.

| Component | Memory |
|---|---|
| PostgreSQL | ~1 GB |
| Redis | ~256 MB |
| MinIO | ~512 MB |
| 15 Phoenix services | ~5.5 GB total |
| OS + k3s overhead | ~1 GB |
| **Total** | **~7.3 GB** |

---

## Step 1: Provision the VPS with k3s

SSH into your VPS and run the provisioning script:

```bash
cd /opt
git clone https://github.com/thirunagariharish/PhoneixClaw.git phoenix
cd phoenix

LETSENCRYPT_EMAIL=admin@yourdomain.com infra/scripts/provision-k3s.sh
```

This installs:
- k3s (single-node with Traefik and servicelb)
- Helm
- Sealed Secrets controller (for encrypted secrets)
- cert-manager (for Let's Encrypt TLS)
- ClusterIssuer `letsencrypt-prod`
- UFW firewall (SSH, HTTP, HTTPS only)

Skip the firewall step if already configured:

```bash
LETSENCRYPT_EMAIL=admin@yourdomain.com infra/scripts/provision-k3s.sh --skip-firewall
```

---

## Step 2: Point Your Domain

In your domain DNS settings, create:

```
A  cashflowus.com      →  YOUR_VPS_IP
A  www.cashflowus.com  →  YOUR_VPS_IP
```

Wait for DNS propagation (usually < 5 minutes).

---

## Step 3: Seal Secrets

Phoenix uses Bitnami SealedSecrets to encrypt sensitive values. From a machine with `kubectl` configured for the cluster and `kubeseal` installed:

```bash
# Install kubeseal if needed
brew install kubeseal  # macOS
# or download from https://github.com/bitnami-labs/sealed-secrets/releases

# Create namespace
kubectl create namespace phoenix

# Fetch the sealing certificate
kubeseal --fetch-cert > /tmp/sealed-secrets-cert.pem

# Seal each secret value
for KEY in POSTGRES_PASSWORD JWT_SECRET_KEY CREDENTIAL_ENCRYPTION_KEY ANTHROPIC_API_KEY \
           MINIO_ROOT_USER MINIO_ROOT_PASSWORD RH_USERNAME RH_PASSWORD RH_TOTP_SECRET DISCORD_BOT_TOKEN; do
  echo "Seal $KEY:"
  read -s VALUE
  SEALED=$(echo -n "$VALUE" | kubeseal --raw \
    --cert /tmp/sealed-secrets-cert.pem \
    --namespace phoenix --name phoenix-secrets --scope namespace-wide)
  echo "$KEY sealed ciphertext: $SEALED"
  echo
done
```

Copy the chart template and replace placeholders:

```bash
cd /opt/phoenix
cp helm/phoenix/templates/sealedsecret.yaml.template helm/phoenix/templates/sealedsecret.yaml
# Edit sealedsecret.yaml: replace each <SEALED_*> with the corresponding ciphertext
kubectl apply -f helm/phoenix/templates/sealedsecret.yaml -n phoenix
```

### Secret generation reference

| Variable | How to generate |
|---|---|
| `POSTGRES_PASSWORD` | `openssl rand -base64 24` |
| `JWT_SECRET_KEY` | `openssl rand -hex 32` |
| `CREDENTIAL_ENCRYPTION_KEY` | `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `ANTHROPIC_API_KEY` | From Anthropic Console |
| `MINIO_ROOT_USER` | Any username (e.g. `minioadmin`) |
| `MINIO_ROOT_PASSWORD` | `openssl rand -base64 24` |
| `RH_USERNAME` | Robinhood account email |
| `RH_PASSWORD` | Robinhood password |
| `RH_TOTP_SECRET` | (Optional) Authenticator app secret |
| `DISCORD_BOT_TOKEN` | From Discord Developer Portal |

---

## Step 4: Deploy the Helm Chart

For the initial cutover (using locally imported images):

```bash
helm install phoenix /opt/phoenix/helm/phoenix \
  -n phoenix --create-namespace --wait --timeout=15m
```

For production (pulling from GHCR):

```bash
helm install phoenix /opt/phoenix/helm/phoenix \
  -f /opt/phoenix/helm/phoenix/values.prod.yaml \
  -n phoenix --create-namespace \
  --set image.tag=latest \
  --wait --timeout=15m
```

### What happens during install

1. Helm pre-install hook runs database migrations (Job)
2. Postgres StatefulSet starts with 10Gi PVC
3. Redis Deployment starts with 256MB memory limit
4. MinIO StatefulSet starts with 5Gi PVC
5. 15 Phoenix service Deployments start
6. edge-nginx Deployment starts with nginx.conf ConfigMap
7. Traefik IngressRoute created for `cashflowus.com` + `www.cashflowus.com`
8. cert-manager provisions Let's Encrypt certificate
9. All pods reach Ready state

---

## Step 5: Verify

```bash
# Check all pods are Running
kubectl get pods -n phoenix

# Check ingress
kubectl get ingressroute -n phoenix

# Check TLS certificate
kubectl get certificate -n phoenix

# View logs
kubectl logs -n phoenix -l app.kubernetes.io/part-of=phoenix --tail=50 --prefix
```

Open `https://cashflowus.com` in your browser. You should see the Phoenix dashboard login page with a valid TLS certificate.

### Quick health check

```bash
# From VPS
kubectl port-forward -n phoenix svc/phoenix-api 8011:8011 &
curl http://localhost:8011/health

# Or via Traefik
curl https://cashflowus.com/api/health
```

---

## Ongoing Operations

### Redeploying (after code changes)

For tagged releases, GitHub Actions CI/CD handles deployment automatically:

```bash
git tag v1.2.3
git push origin v1.2.3
```

The workflow builds all images, pushes to GHCR, SSHs to the VPS, and runs:

```bash
helm upgrade --install phoenix /opt/phoenix/helm/phoenix \
  -f /opt/phoenix/helm/phoenix/values.prod.yaml \
  -n phoenix --set image.tag=v1.2.3 \
  --wait --timeout=15m
```

Manual upgrade:

```bash
cd /opt/phoenix
git pull
helm upgrade phoenix helm/phoenix -f helm/phoenix/values.prod.yaml -n phoenix --wait
```

### Viewing Logs

```bash
# All Phoenix logs
kubectl logs -n phoenix -l app.kubernetes.io/part-of=phoenix --tail=100 -f --prefix

# Specific service
kubectl logs -n phoenix deployment/phoenix-api --tail=100 -f
```

### Scaling (if your VPS has more resources)

Edit `helm/phoenix/values.yaml` or pass `--set` flags:

```bash
helm upgrade phoenix helm/phoenix -f helm/phoenix/values.prod.yaml -n phoenix \
  --set resources.api.memory=4Gi \
  --wait
```

### Updating Environment Variables

For non-secret config, edit `helm/phoenix/values.prod.yaml`:

```yaml
appConfig:
  enableTrading: "true"
  dryRunMode: "false"
```

Then:

```bash
helm upgrade phoenix helm/phoenix -f helm/phoenix/values.prod.yaml -n phoenix --wait
```

For secrets, re-seal and re-apply the SealedSecret YAML, then restart affected pods:

```bash
kubectl rollout restart deployment/phoenix-api -n phoenix
```

### Backups

Postgres backup:

```bash
kubectl exec -n phoenix postgres-0 -- pg_dump -U phoenixtrader phoenixtrader --format=custom > backup_$(date +%Y%m%d).dump
```

Restore:

```bash
kubectl cp backup_20260504.dump phoenix/postgres-0:/tmp/
kubectl exec -n phoenix postgres-0 -- pg_restore -U phoenixtrader -d phoenixtrader --clean /tmp/backup_20260504.dump
```

### Monitoring

```bash
# Resource usage
kubectl top pods -n phoenix

# Events
kubectl get events -n phoenix --sort-by='.lastTimestamp' | tail -20

# Disk usage
df -h
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| **Pods stuck in Pending** | Check PVC binding: `kubectl describe pvc -n phoenix`. Ensure storage class exists. |
| **"502 Bad Gateway"** | Pods still starting. Wait 1-2 min. Check `kubectl get pods -n phoenix` for unhealthy pods. |
| **Dashboard loads but API calls fail** | Verify `phoenix-api` is Running: `kubectl logs -n phoenix deployment/phoenix-api`. |
| **"Database connection refused"** | Check Postgres: `kubectl logs -n phoenix postgres-0`. Verify SealedSecret unsealed correctly: `kubectl get secret phoenix-secrets -n phoenix -o yaml`. |
| **TLS certificate not issuing** | Check cert-manager logs: `kubectl logs -n cert-manager -l app=cert-manager`. Verify ClusterIssuer: `kubectl describe clusterissuer letsencrypt-prod`. |
| **Out of disk space** | Clean containerd: `k3s crictl rmi --prune`. Clean PVCs: `kubectl delete pvc <unused-pvc> -n phoenix`. |
| **Out of memory** | Check `kubectl top pods -n phoenix`. Reduce resource limits in values.yaml or scale down replicas. |

---

## Architecture on VPS

```
Internet
   │
   ▼
Traefik (k3s built-in) ─── HTTPS ───▶ edge-nginx (ClusterIP :80)
                                          │
                                ┌─────────┤ /api/* /auth/* /ws/*
                                ▼         │
                          phoenix-api (:8011)  phoenix-ws-gateway (:8031)
                                │             phoenix-dashboard (:80)
               ┌────────────────┼────────────────┐
               ▼                ▼                 ▼
         phoenix-execution  phoenix-llm-gateway  phoenix-broker-gateway
         phoenix-automation phoenix-inference   phoenix-agent-orchestrator
         ...                                     ...
               │
  ┌────────────┼──────────┐
  ▼            ▼           ▼
postgres    redis       minio
(StatefulSet) (Deployment) (StatefulSet)
```

All services communicate on the internal Kubernetes ClusterIP network. Only Traefik exposes HTTPS to the internet via the IngressRoute.

---

## CI/CD Workflow

See `.github/workflows/cd.yml`. Required GitHub secrets:
- `K3S_HOST` — VPS IP or hostname
- `K3S_SSH_KEY` — Private SSH key for `root@VPS`

The workflow:
1. Builds 14 service images on `v*` tag push
2. Pushes to `ghcr.io/thirunagariharish/phoneixclaw/phoenix-*`
3. SCPs the Helm chart to `/opt/phoenix` on the VPS
4. Runs `helm upgrade --install` with the new tag

---

## Uninstalling

```bash
helm uninstall phoenix -n phoenix
kubectl delete namespace phoenix
```

This does NOT delete PVCs. To delete all data:

```bash
kubectl delete pvc -n phoenix --all
```
