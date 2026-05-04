# Phoenix Helm Chart

Kubernetes deployment for the Phoenix Trade Bot platform on k3s.

## Prerequisites

- k3s cluster with Traefik (default) and cert-manager installed
- kubectl configured for the cluster
- kubeseal CLI for sealed-secrets
- Sealed Secrets controller installed in kube-system namespace

## Installation

### 1. Create namespace

```bash
kubectl create namespace phoenix
```

### 2. Seal secrets

The chart uses Bitnami SealedSecrets to encrypt sensitive values. Follow these steps:

```bash
# Fetch the sealing certificate from the cluster
kubeseal --fetch-cert > /tmp/sealed-secrets-cert.pem

# For each of the 10 secret keys, seal the value
read -s VALUE
echo -n "$VALUE" | kubeseal --raw \
  --cert /tmp/sealed-secrets-cert.pem \
  --namespace phoenix \
  --name phoenix-secrets \
  --scope namespace-wide

# The command outputs a sealed ciphertext - copy it into the template
```

The 9 secret keys required:
- `POSTGRES_PASSWORD`
- `JWT_SECRET_KEY`
- `CREDENTIAL_ENCRYPTION_KEY`
- `ANTHROPIC_API_KEY`
- `MINIO_ROOT_USER`
- `MINIO_ROOT_PASSWORD`
- `RH_USERNAME`
- `RH_PASSWORD`
- `RH_TOTP_SECRET`

Discord bot tokens are managed at runtime via the dashboard's Connectors panel and stored encrypted in the `connectors` table — they are not chart-level secrets.

Edit `templates/sealedsecret.yaml.template`, replace each `<SEALED_*>` placeholder with the corresponding ciphertext, and save the file as `templates/sealedsecret.yaml`.

Apply the SealedSecret:

```bash
kubectl apply -f templates/sealedsecret.yaml -n phoenix
```

### 3. Install the chart

For local/cutover (using pre-imported images):

```bash
helm install phoenix . -n phoenix --create-namespace --wait --timeout=15m
```

For production (pulling from GHCR):

```bash
helm install phoenix . -f values.prod.yaml -n phoenix --create-namespace --wait --timeout=15m
```

## Upgrading

```bash
helm upgrade phoenix . -f values.prod.yaml -n phoenix --wait --timeout=15m
```

To set the image tag dynamically (e.g., from CI):

```bash
helm upgrade phoenix . -f values.prod.yaml -n phoenix --set image.tag=v1.2.3 --wait --timeout=15m
```

## Values

See `values.yaml` for local defaults and `values.prod.yaml` for production overrides.

Key configuration options:
- `image.repository` - Image repository path
- `image.tag` - Image tag
- `image.pullPolicy` - Pull policy (IfNotPresent for local, Always for prod)
- `appConfig.corsOrigins` - CORS allowed origins
- `appConfig.enableTrading` - Enable live trading (default: false)
- `appConfig.dryRunMode` - Dry run mode (default: true)
- `resources.*` - Memory limits per service

## Architecture

15 Phoenix services + 3 infrastructure services (Postgres, Redis, MinIO) + edge-nginx reverse proxy + Traefik IngressRoute.

See `ADR.md` for architecture decision records.

## Uninstalling

```bash
helm uninstall phoenix -n phoenix
kubectl delete namespace phoenix
```

This does NOT delete PVCs. To delete all data:

```bash
kubectl delete pvc -n phoenix --all
```
