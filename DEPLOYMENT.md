# DEPLOYMENT — Phoenix Trade Bot

The 60-second deploy reference. For deep operational knowledge, recovery, and bug-fix history, read [`docs/operations/deployment-guide.md`](docs/operations/deployment-guide.md) (~400 lines).

---

## TL;DR — every routine deploy

```bash
# Local dev: make a change, push, done.
git push origin main
```

GitHub Actions auto-builds 15 images, pushes to `ghcr.io/thirunagariharish/phoneixclaw/phoenix-<svc>:main-<sha7>`, SCPs the chart to the VPS, runs `helm upgrade --install`. Takes 12-18 min. Watch at https://github.com/ThirunagariHarish/PhoneixClaw/actions.

For an explicit version cut:

```bash
git tag -a v1.2.3 -m "release notes"
git push origin v1.2.3
```

Same flow, image tag is `v1.2.3` instead of `main-<sha>`.

---

## Where things live

| Thing | Location |
|---|---|
| Public URL | `https://cashflowus.com/` (also `www.cashflowus.com`) |
| Public health | `curl -fsS https://cashflowus.com/health | jq` |
| VPS | `ssh -i ~/.ssh/coolify_deploy root@69.62.86.166` (sshd intermittently throttles — retry) |
| Cluster namespace | `phoenix` |
| Helm release | `phoenix` (`helm list -n phoenix`) |
| Image registry | `ghcr.io/thirunagariharish/phoneixclaw/phoenix-<svc>` (tag `main-<sha7>` or `v*`) |
| Repo | `ThirunagariHarish/PhoneixClaw` (private) |
| CI workflow | `.github/workflows/cd.yml` |
| Secrets backup | `~/Phoenix-DR/sealed-secrets-key.<ts>.backup.yaml` (encrypt with `gpg -c`) |

---

## Prerequisites for CI to work

These three GitHub Actions secrets must exist at https://github.com/ThirunagariHarish/PhoneixClaw/settings/secrets/actions:

| Secret | Value | Notes |
|---|---|---|
| `K3S_HOST` | `69.62.86.166` | VPS IP |
| `K3S_SSH_KEY` | OpenSSH private key (raw or base64) | The workflow accepts both. Base64 is safer (`base64 < ~/.ssh/coolify_deploy | pbcopy`). |
| `GHCR_PAT` | Classic PAT with `repo` + `read:packages` + `write:packages` | Required because the default `GITHUB_TOKEN` can't write to packages not yet linked to the repo. |

---

## Deploying for the first time on a fresh cluster (rare)

Use `infra/scripts/provision-k3s.sh` to bootstrap k3s + sealed-secrets + cert-manager + ClusterIssuer + UFW on a fresh Ubuntu VPS. Then follow the bootstrap steps in [`docs/operations/deployment-guide.md`](docs/operations/deployment-guide.md) §5.2.

---

## Backups (do this monthly)

Off-cluster sealed-secrets backup:

```bash
./infra/scripts/backup-sealed-secrets-key.sh
gpg -c ~/Phoenix-DR/sealed-secrets-key.*.backup.yaml
```

Postgres has a daily CronJob (`postgres-backup`, 03:00 UTC) that pg_dumps to MinIO inside the cluster. **That's not a real backup** — if the cluster dies, the dumps die with it. For real DR, also pull a periodic dump off-cluster:

```bash
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 \
  "kubectl exec -n phoenix postgres-0 -- pg_dump -U phoenixtrader -d phoenixtrader --format=custom" \
  > ~/Phoenix-DR/postgres-$(date +%Y%m%dT%H%M%S).dump
```

---

## When something goes wrong

### CD pipeline failed

Click the failed run at https://github.com/ThirunagariHarish/PhoneixClaw/actions. The most common failures:

1. **`denied: permission_denied: write_package`** — `GHCR_PAT` is missing/expired. Create a new classic PAT, update the secret.
2. **`Load key … error in libcrypto` / `Permission denied (publickey)`** — `K3S_SSH_KEY` got newline-mangled by the GitHub web form. Re-paste as base64: `base64 < ~/.ssh/coolify_deploy | pbcopy`.
3. **`helm upgrade timed out`** — usually a pod is in CrashLoopBackOff. SSH to VPS, check `kubectl get pods -n phoenix`. Common: missing DB schema (run `kubectl exec -n phoenix deploy/phoenix-api -- python scripts/docker_migrate.py`).

### Deployed but pods crashlooping

```bash
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166
kubectl get pods -n phoenix
kubectl logs -n phoenix deploy/<failing-deploy> --tail=50
```

### Public URL returns 502 / down

```bash
curl -fsS https://cashflowus.com/health | jq
# If the api endpoint is reachable but reports unhealthy components,
# check the named subsystem (db / redis / ingestion).
```

### Database lost data

If `kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -tAc "SELECT COUNT(*) FROM users"` returns 0, the postgres PVC was wiped. Restore:

```bash
# Re-create schema
kubectl exec -n phoenix deploy/phoenix-api -- python scripts/docker_migrate.py

# If you have an off-cluster pg_dump, restore it:
kubectl cp ~/Phoenix-DR/postgres-<ts>.dump phoenix/postgres-0:/tmp/restore.dump
kubectl exec -n phoenix postgres-0 -- \
  pg_restore -U phoenixtrader -d phoenixtrader --clean --if-exists /tmp/restore.dump

# Otherwise: re-bootstrap admin user (see deployment-guide.md §7),
# user re-adds connectors via dashboard, you re-load seed data.
```

### Sealed-secret can't decrypt (cluster rebuilt)

The Bitnami sealed-secrets controller's master key was destroyed with the cluster, so existing ciphertexts in the repo no longer decrypt. Restore from your off-cluster backup:

```bash
gpg -d ~/Phoenix-DR/sealed-secrets-key.<ts>.backup.yaml.gpg | \
  ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 "kubectl apply -f -"
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 \
  "kubectl rollout restart -n kube-system deploy/sealed-secrets-controller"
```

---

## What NOT to do

- **Never** `helm uninstall phoenix` unless you mean to lose the SealedSecret resource (it's helm-owned). If you must, re-`kubectl apply -f helm/phoenix/templates/sealedsecret.yaml` first.
- **Never** delete `pgdata-postgres-0` PVC unless you have a fresh `pg_dump` in `~/Phoenix-DR/`. Lost once today (2026-05-04); recovered seed data but lost users + connectors.
- **Never** add a second deployer (e.g., re-register an argocd Application). CI is the single source of truth for image tags. We tried argocd earlier — it fought CI on `image.tag` and broke deploys.
- **Never** push without `GHCR_PAT` set if you've added new images. Default `GITHUB_TOKEN` can't write to unlinked packages.

---

## Verifying a deploy succeeded

```bash
# CI green
gh run list --workflow=cd.yml --limit 1 -R ThirunagariHarish/PhoneixClaw

# Public health
curl -fsS https://cashflowus.com/health | jq

# Cluster has the right image tag
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 \
  "kubectl get deploy -n phoenix -o jsonpath='{range .items[*]}{.metadata.name}: {.spec.template.spec.containers[0].image}{\"\\n\"}{end}'"

# All pods Running
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 \
  "kubectl get pods -n phoenix --no-headers | awk '{print \$3}' | sort | uniq -c"
```

---

## Full runbook

[`docs/operations/deployment-guide.md`](docs/operations/deployment-guide.md) covers everything else: cluster inventory, all 18 services and their ports, common operations (logs, exec, port-forward), 8+ traps with fixes, bootstrap admin user via `PHOENIX_ADMIN_INVITE_CODE`, broker-gateway endpoint reference, disaster recovery, postgres-backup details, all known issues.

If you're a new session, read that file first.
