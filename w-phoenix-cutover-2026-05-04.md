# Track W cutover plan (DRAFT — reviewed/finalized 2026-05-04)

> **Status:** DRAFT. Authored by Phoenix-chart-draft 2026-05-04 from the
> recon doc (`docs/reviews/phoenix-recon-2026-05-04.md`) and the DRAFT
> Helm chart (`helm/phoenix/`). Operator MUST review every step and
> resolve all `<...>` placeholders before execution.

## Context

- **Source:** Phoenix on Coolify, single-host (Hostinger VPS
  `srv1349789.hstgr.cloud` / `69.62.86.166`), 15 containers under app
  uuid `tcgk8444kk0cscksg8448o48`.
- **Target:** k3s on the same VPS, namespace `phoenix`, Helm release
  `phoenix` from chart `helm/phoenix/`.
- **Public hostname:** `cashflowus.com` (+ `www.cashflowus.com`),
  unchanged DNS.
- **Datasets:** PG ~14 MiB, MinIO ~104 KiB, Redis cache ~8 KiB
  (skipped). Migration window is dominated by traefik flip + soak, not
  data movement.

---

## Pre-cutover (T-30 min)

1. **Verify Phoenix on Coolify is healthy.** SSH to VPS, run:

   ```sh
   docker ps --filter label=coolify.applicationId=5 \
     --format 'table {{.Names}}\t{{.Status}}'
   ```

   All 15 containers should be `(healthy)` or `Up`. **Known unhealthy
   from recon (acceptable):** `phoenix-broker-gateway`,
   `phoenix-discord-ingestion` — confirm they're the same root cause as
   recon, not a new failure.

2. **Save each Phoenix image to a tar.** (~12 GB total — make sure
   `/root/phoenix-images/` has free space.)

   ```sh
   mkdir -p /root/phoenix-images
   for img in $(docker images --format '{{.Repository}}:{{.Tag}}' | grep -i 'tcgk8444kk0cscksg8448o48'); do
     fname=$(echo "$img" | tr '/:' '__')
     docker save "$img" -o /root/phoenix-images/${fname}.tar
   done
   ls -lh /root/phoenix-images/
   ```

3. **Re-tag each image to `phoenix/<service>:local`** (matches the
   chart's `image:` defaults). The chart sets `imagePullPolicy:
   IfNotPresent` so the kubelet uses the locally-imported image.

   ```sh
   declare -A MAP=(
     [tcgk8444kk0cscksg8448o48_phoenix-api]=phoenix/phoenix-api
     [tcgk8444kk0cscksg8448o48_phoenix-dashboard]=phoenix/phoenix-dashboard
     [tcgk8444kk0cscksg8448o48_phoenix-ws-gateway]=phoenix/phoenix-ws-gateway
     [tcgk8444kk0cscksg8448o48_phoenix-llm-gateway]=phoenix/phoenix-llm-gateway
     [tcgk8444kk0cscksg8448o48_phoenix-broker-gateway]=phoenix/phoenix-broker-gateway
     [tcgk8444kk0cscksg8448o48_phoenix-execution]=phoenix/phoenix-execution
     [tcgk8444kk0cscksg8448o48_phoenix-automation]=phoenix/phoenix-automation
     [tcgk8444kk0cscksg8448o48_phoenix-discord-ingestion]=phoenix/phoenix-discord-ingestion
     [tcgk8444kk0cscksg8448o48_phoenix-feature-pipeline]=phoenix/phoenix-feature-pipeline
     [tcgk8444kk0cscksg8448o48_phoenix-inference-service]=phoenix/phoenix-inference-service
     [tcgk8444kk0cscksg8448o48_phoenix-agent-orchestrator]=phoenix/phoenix-agent-orchestrator
     [tcgk8444kk0cscksg8448o48_phoenix-prediction-monitor]=phoenix/phoenix-prediction-monitor
     [tcgk8444kk0cscksg8448o48_phoenix-backtesting]=phoenix/phoenix-backtesting
     [tcgk8444kk0cscksg8448o48_nginx]=phoenix/nginx
   )
   for src in "${!MAP[@]}"; do
     # find the actual tag (e.g. 417261d0…)
     full=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep "^$src:" | head -1)
     [ -z "$full" ] && { echo "SKIP $src (not found)"; continue; }
     docker tag "$full" "${MAP[$src]}:local"
     echo "tagged ${MAP[$src]}:local <- $full"
   done
   ```

4. **Import each tar (or freshly tagged image) into k3s containerd.**
   Two options — either re-save the freshly tagged image, or use the
   existing tars and re-tag inside ctr:

   ```sh
   # option A: re-save with new tag, then import
   for tag in $(docker images --format '{{.Repository}}:{{.Tag}}' | grep '^phoenix/.*:local$'); do
     fname=$(echo "$tag" | tr '/:' '__')
     docker save "$tag" -o /root/phoenix-images/${fname}.tar
     sudo k3s ctr images import "/root/phoenix-images/${fname}.tar"
   done
   sudo k3s ctr images list | grep '^phoenix/' | wc -l   # expect 14
   ```

5. **Pre-pull infra images into k3s** (timescaledb, redis, minio — these
   pull from public registries and the chart still expects
   `IfNotPresent`, so seed them now):

   ```sh
   sudo k3s ctr images pull docker.io/timescale/timescaledb:latest-pg16
   sudo k3s ctr images pull docker.io/library/redis:7-alpine
   sudo k3s ctr images pull docker.io/minio/minio:latest
   ```

---

## Postgres data dump

6. **`pg_dump` from the Coolify TimescaleDB container.** Note from recon:
   the superuser `postgres` does NOT exist; use `phoenixtrader`.

   ```sh
   PG=postgres-tcgk8444kk0cscksg8448o48-045348306127  # confirm via docker ps
   mkdir -p /root/phoenix-data
   docker exec "$PG" pg_dump \
     -U phoenixtrader \
     -d phoenixtrader \
     --format=custom \
     --file=/tmp/phoenixtrader.dump
   docker cp "$PG:/tmp/phoenixtrader.dump" /root/phoenix-data/
   ls -lh /root/phoenix-data/phoenixtrader.dump   # expect ~5-10 MiB compressed
   ```

7. **MinIO source dump** (104 KiB — trivial; skip if empty).

   ```sh
   MINIO=minio-tcgk8444kk0cscksg8448o48-045348318076
   docker exec "$MINIO" mc alias set src http://localhost:9000 \
     "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
   docker exec "$MINIO" mc ls --recursive src/  | tee /root/phoenix-data/minio-listing.txt
   ```

---

## Apply secrets and install the Helm chart

8. **Generate sealed-secrets ciphertexts.** On a host with `kubeseal`
   and a kube context for the target k3s cluster:

   ```sh
   kubectl create namespace phoenix --dry-run=client -o yaml | kubectl apply -f -
   kubeseal --fetch-cert > /tmp/sealed-secrets-cert.pem

   # for each KEY in helm/phoenix/sealedsecret.yaml.template:
   read -s VALUE
   echo -n "$VALUE" | kubeseal --raw \
     --cert /tmp/sealed-secrets-cert.pem \
     --namespace phoenix --name phoenix-secrets
   # copy the resulting ciphertext into the appropriate slot of
   # helm/phoenix/sealedsecret.yaml.template (rename to .yaml first).
   ```

   Apply it:

   ```sh
   kubectl apply -f helm/phoenix/sealedsecret.yaml -n phoenix
   ```

9. **Install the chart.** First do a dry-run to confirm rendering on the
   target cluster:

   ```sh
   helm template phoenix helm/phoenix/ \
     -f helm/phoenix/values.prod.yaml \
     -n phoenix --validate

   helm install phoenix helm/phoenix/ \
     -f helm/phoenix/values.prod.yaml \
     -n phoenix --create-namespace \
     --wait --timeout=15m
   ```

   Watch with: `kubectl get pods -n phoenix -w`.

10. **Wait for `timescaledb-0` Ready.** It will start with an empty DB.

    ```sh
    kubectl wait pod/timescaledb-0 -n phoenix --for=condition=Ready --timeout=5m
    ```

---

## Restore Postgres dump into k3s

11. **Copy the dump in and restore.**

    ```sh
    kubectl cp /root/phoenix-data/phoenixtrader.dump phoenix/timescaledb-0:/tmp/
    kubectl exec -n phoenix timescaledb-0 -- \
      pg_restore -U phoenixtrader -d phoenixtrader \
        --clean --if-exists \
        /tmp/phoenixtrader.dump
    ```

12. **Verify row counts on key tables** (compare against the source).

    ```sh
    kubectl exec -n phoenix timescaledb-0 -- psql -U phoenixtrader -d phoenixtrader -c \
      "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 20;"
    docker exec "$PG" psql -U phoenixtrader -d phoenixtrader -c \
      "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 20;"
    ```

    Numbers should match exactly. If not — STOP, rollback (no traffic
    has shifted yet, easy to abort).

13. **MinIO mirror** (104 KiB — usually a no-op).

    ```sh
    # from VPS:
    mc alias set coolify  http://<coolify-minio-ip>:9000  "$ROOT_USER" "$ROOT_PASS"
    mc alias set k3s      http://<k3s-minio-svc-ip>:9000   "$ROOT_USER" "$ROOT_PASS"
    mc mirror coolify/  k3s/
    ```

---

## Smoke (Phoenix on k3s, traffic still on Coolify)

14. **Port-forward the dashboard locally** and hit `/`.

    ```sh
    kubectl port-forward -n phoenix svc/edge-nginx 8080:80 &
    curl -fsS http://127.0.0.1:8080/ | head -5
    # expect HTML SPA shell, 200
    ```

15. **Walk through every Service.**

    ```sh
    for svc in phoenix-api phoenix-ws-gateway phoenix-llm-gateway \
               phoenix-broker-gateway phoenix-execution phoenix-automation \
               phoenix-discord-ingestion phoenix-feature-pipeline \
               phoenix-inference-service phoenix-agent-orchestrator \
               phoenix-prediction-monitor phoenix-backtesting; do
      echo "--- $svc ---"
      kubectl get svc -n phoenix "$svc" -o jsonpath='{.spec.clusterIP}:{.spec.ports[0].port}'
    done
    kubectl get pods -n phoenix
    ```

    All 15 pods should be `Running` (the two pre-existing unhealthy
    services from recon will likely still be unhealthy on k3s for the
    same root cause — that is acceptable; they were unhealthy on Coolify
    too).

16. **Verify intra-cluster DNS** by exec-ing into the api pod:

    ```sh
    kubectl exec -n phoenix deploy/phoenix-api -- \
      python -c "import urllib.request; print(urllib.request.urlopen('http://postgres:5432').read()[:0] or 'reachable')" || true
    kubectl exec -n phoenix deploy/phoenix-api -- \
      python -c "import urllib.request; print(urllib.request.urlopen('http://redis:6379').read()[:0] or 'reachable')" || true
    ```

---

## Cutover

17. **Stop Coolify Phoenix containers.** Phoenix is DOWN from this point
    until step 19 reroutes traffic.

    ```sh
    docker ps --filter label=coolify.applicationId=5 -q | xargs -r docker stop
    ```

18. **Reroute Coolify Traefik to the in-cluster Phoenix service.** Per
    recon §Networking, Phoenix has NO static dynamic-yaml file in
    `/data/coolify/proxy/dynamic/` — its routing was via container
    labels. We add a new dynamic-config file pointing the public host
    at the k3s NodePort or ClusterIP-equivalent:

    ```yaml
    # /data/coolify/proxy/dynamic/phoenix-k3s.yml
    http:
      routers:
        phoenix-k3s:
          rule: "Host(`cashflowus.com`) || Host(`www.cashflowus.com`)"
          service: phoenix-k3s-svc
          entryPoints: [http, https]
          tls: { certResolver: letsencrypt }
      services:
        phoenix-k3s-svc:
          loadBalancer:
            servers:
              - url: "http://<EDGE_NGINX_NODEPORT_OR_CLUSTERIP>:80"
    ```

    To get the right URL:
    - **NodePort path:** `kubectl patch svc edge-nginx -n phoenix -p
      '{"spec":{"type":"NodePort"}}'` → use `127.0.0.1:<nodePort>`.
    - **ClusterIP path:** read `kubectl get svc edge-nginx -n phoenix -o
      jsonpath='{.spec.clusterIP}'` and route to that. Works because
      Coolify Traefik runs on the host network and k3s ClusterIPs are
      reachable from the host.

19. **Reload Coolify Traefik.** It auto-reloads dynamic-config files; if
    not:

    ```sh
    docker kill -s HUP coolify-proxy   # SIGHUP triggers reload
    ```

20. **Verify the public URL is now serving k3s Phoenix.**

    ```sh
    curl -fsS https://cashflowus.com/ | head -5
    curl -fsS https://www.cashflowus.com/ | head -5
    ```

    Phoenix is UP again. Track elapsed downtime: typically < 60 s.

21. **Soak 30 min.** Watch:

    ```sh
    kubectl logs -n phoenix -l app.kubernetes.io/part-of=phoenix \
      --tail=50 --follow --prefix
    ```

    Look for repeated 5xx, restart loops, OOMKills.

---

## Rollback (if cutover fails)

If anything's wrong in steps 17–21:

1. **Remove the new dynamic config:**
   `rm /data/coolify/proxy/dynamic/phoenix-k3s.yml`
2. **Restart Coolify Phoenix containers:**
   `docker ps -a --filter label=coolify.applicationId=5 -q | xargs -r docker start`
3. **Reload Coolify Traefik:** `docker kill -s HUP coolify-proxy`
4. **Verify:** `curl -fsS https://cashflowus.com/`
5. Phoenix is back on Coolify. Investigate failures via
   `kubectl logs`, fix the chart values / sealed-secret values, retry
   the next day. The k3s release stays running so you can continue to
   smoke-test it without affecting prod.

---

## Post-cutover (24 h soak)

- Monitor `kubectl top pods -n phoenix` for memory pressure (8 GB VPS,
  k3s + Coolify infra both resident).
- `kubectl get events -n phoenix --sort-by='.lastTimestamp' | tail -50`
  every few hours.
- Spot-check Phoenix dashboard end-to-end (login, run a query, place a
  paper trade — `DRY_RUN_MODE=true` is still on).
- After 24 h with no regressions:
  - Flip `ENABLE_TRADING=true` / `DRY_RUN_MODE=false` (if intended) via
    `helm upgrade phoenix helm/phoenix/ -f helm/phoenix/values.prod.yaml
    --set appConfig.ENABLE_TRADING=true --set appConfig.DRY_RUN_MODE=false`.
  - Proceed to **Track X-final** (decommission Coolify Phoenix entirely
    — `docker rm` the stopped containers, `docker volume rm` the
    pgdata/miniodata/ollama-data volumes, remove the Coolify
    application via UI).

---

## Open issues / follow-ups

1. **`automation` worker has no HTTP port in compose.** The Helm chart
   exposes a placeholder port + probe; almost certainly wrong. Operator
   must either remove probes for that Deployment or expose a real
   healthcheck before deploy.
2. **`broker-gateway` rh_tokens persistence.** DRAFT mounts emptyDir; an
   MFA SMS will fire on every pod restart. Convert to a 100 Mi PVC
   before deploying.
3. **Ollama disabled.** `OLLAMA_BASE_URL` resolves to NXDOMAIN until
   Ollama is re-introduced. LLM-gateway should fall back to Anthropic.
4. **Two pre-existing unhealthy containers.** Diagnose root cause before
   migration so we don't carry the same brokenness into k3s.
5. **Coolify Traefik dynamic-config file path** must be confirmed on the
   actual VPS — there is no Phoenix entry there today, so step 18 is
   creating a brand-new file.
