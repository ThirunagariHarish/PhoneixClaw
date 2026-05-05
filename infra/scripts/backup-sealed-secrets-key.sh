#!/bin/bash
#
# backup-sealed-secrets-key.sh
#
# Backs up the Bitnami sealed-secrets controller's master encryption key
# from the k3s cluster to a local directory outside the repository.
#
# WHY THIS MATTERS:
# If the k3s cluster is destroyed and rebuilt, the new sealed-secrets controller
# generates a fresh master key, and ALL existing SealedSecret ciphertexts in the
# repo become permanently undecryptable. Phoenix has 6 production secrets:
#   - POSTGRES_PASSWORD
#   - JWT_SECRET_KEY
#   - CREDENTIAL_ENCRYPTION_KEY (Fernet key for broker/Discord creds in DB)
#   - ANTHROPIC_API_KEY
#   - MINIO_ROOT_USER
#   - MINIO_ROOT_PASSWORD
#
# Losing CREDENTIAL_ENCRYPTION_KEY is especially painful: all stored Robinhood
# and Discord credentials in the database become unreadable.
#
# WHEN TO RUN:
#   - After initial cluster setup (one-time)
#   - After any kube-system upgrade or sealed-secrets controller reinstall
#   - Quarterly as part of DR hygiene (recommended)
#
# HOW TO RESTORE (disaster recovery):
#   1. SSH to the fresh cluster: ssh -i ~/.ssh/coolify_deploy root@69.62.86.166
#   2. Decrypt the backup: gpg -d ~/Phoenix-DR/sealed-secrets-key.<timestamp>.backup.yaml.gpg > /tmp/key.yaml
#   3. Apply it: kubectl create -f /tmp/key.yaml
#   4. Restart the controller: kubectl rollout restart -n kube-system deployment/sealed-secrets-controller
#   5. The controller picks up the restored key, and existing ciphertexts decrypt again.
#

set -euo pipefail

# Constants
VPS_HOST="69.62.86.166"
SSH_KEY="$HOME/.ssh/coolify_deploy"
BACKUP_DIR="$HOME/Phoenix-DR"
TIMESTAMP=$(date +%Y%m%dT%H%M%S)
BACKUP_FILE="$BACKUP_DIR/sealed-secrets-key.$TIMESTAMP.backup.yaml"

# Ensure backup directory exists with secure permissions
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# Pull the secret from the cluster
echo "Pulling sealed-secrets master key from k3s cluster at $VPS_HOST..."
ssh -i "$SSH_KEY" "root@$VPS_HOST" \
  "kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml" \
  > "$BACKUP_FILE"

# Secure the backup file
chmod 600 "$BACKUP_FILE"

# Verify the file is valid YAML
if ! head -1 "$BACKUP_FILE" | grep -q "apiVersion"; then
  echo "ERROR: Backup file does not appear to be valid YAML" >&2
  exit 1
fi

FILE_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo ""
echo "Backup complete:"
echo "  File: $BACKUP_FILE"
echo "  Size: $FILE_SIZE"
echo "  Mode: $(stat -f '%A' "$BACKUP_FILE") (owner read/write only)"
echo ""
echo "IMPORTANT: This file contains the plaintext master encryption key."
echo "Encrypt it before storing in the cloud or other shared locations:"
echo ""
echo "  gpg -c \"$BACKUP_FILE\""
echo ""
echo "Then delete the unencrypted file and store the .gpg version securely"
echo "(cloud storage, password manager, hardware key, etc.)."
echo ""

exit 0
