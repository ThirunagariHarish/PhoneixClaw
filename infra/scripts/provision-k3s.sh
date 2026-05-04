#!/usr/bin/env bash
set -euo pipefail

SKIP_FIREWALL=false
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-}"

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]

Provision a fresh Ubuntu VPS with k3s, cert-manager, sealed-secrets, and firewall.

Prerequisites:
  - Fresh Ubuntu 20.04+ VPS
  - root user or sudo access
  - LETSENCRYPT_EMAIL environment variable set

Options:
  --skip-firewall    Skip UFW firewall configuration
  -h, --help         Show this help message

Environment:
  LETSENCRYPT_EMAIL  Email for Let's Encrypt cert notifications (required)

Example:
  LETSENCRYPT_EMAIL=admin@example.com $0
  LETSENCRYPT_EMAIL=admin@example.com $0 --skip-firewall
EOF
  exit 0
}

for arg in "$@"; do
  case $arg in
    --skip-firewall) SKIP_FIREWALL=true ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $arg"; usage ;;
  esac
done

if [ -z "$LETSENCRYPT_EMAIL" ]; then
  echo "ERROR: LETSENCRYPT_EMAIL environment variable is required"
  exit 1
fi

echo "=== Phoenix k3s Provisioning ==="
echo "Email: $LETSENCRYPT_EMAIL"
echo "Skip firewall: $SKIP_FIREWALL"
echo

echo "[1/6] Installing k3s (single-node with Traefik + servicelb)..."
if command -v k3s &>/dev/null; then
  echo "k3s already installed, skipping"
else
  curl -sfL https://get.k3s.io | sh -
  echo "Waiting for k3s to be ready..."
  sleep 10
  kubectl wait --for=condition=Ready nodes --all --timeout=120s
fi

echo "[2/6] Installing Helm..."
if command -v helm &>/dev/null; then
  echo "Helm already installed, skipping"
else
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

echo "[3/6] Installing sealed-secrets controller..."
if kubectl get deployment sealed-secrets-controller -n kube-system &>/dev/null; then
  echo "Sealed-secrets controller already installed, skipping"
else
  helm repo add sealed-secrets https://bitnami-labs.github.io/sealed-secrets
  helm repo update
  helm install sealed-secrets sealed-secrets/sealed-secrets -n kube-system --wait
fi

echo "[4/6] Installing cert-manager..."
if kubectl get namespace cert-manager &>/dev/null; then
  echo "cert-manager already installed, skipping"
else
  kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.4/cert-manager.yaml
  echo "Waiting for cert-manager to be ready..."
  kubectl wait --for=condition=Available deployment --all -n cert-manager --timeout=120s
fi

echo "[5/6] Creating ClusterIssuer letsencrypt-prod..."
cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: $LETSENCRYPT_EMAIL
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
    - http01:
        ingress:
          class: traefik
EOF

if [ "$SKIP_FIREWALL" = true ]; then
  echo "[6/6] Skipping firewall configuration (--skip-firewall)"
else
  echo "[6/6] Configuring UFW firewall (SSH, HTTP, HTTPS)..."
  if command -v ufw &>/dev/null; then
    ufw --force reset
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow 22/tcp comment 'SSH'
    ufw allow 80/tcp comment 'HTTP'
    ufw allow 443/tcp comment 'HTTPS'
    ufw --force enable
    ufw status verbose
  else
    echo "UFW not installed, skipping firewall config"
  fi
fi

echo
echo "=== Provisioning complete ==="
echo
kubectl get nodes
echo
kubectl get pods -A
echo
echo "Next steps:"
echo "  1. Configure Phoenix secrets with kubeseal"
echo "  2. helm install phoenix /path/to/chart -n phoenix --create-namespace --wait"
