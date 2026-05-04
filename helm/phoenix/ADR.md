# Architecture Decision Records — Phoenix k3s Helm Chart

## 1. Single chart vs umbrella

**Decision:** Single chart containing all 15 services.

**Rationale:** 15 services are manageable in a single chart on a single-node k3s cluster. Umbrella chart structure adds complexity around value-passing between subcharts with no benefit at this scale. If Phoenix grows to multi-namespace or multi-team ownership, revisit with subchart per service category.

## 2. HTTP services vs worker template shape

**Decision:** HTTP services receive liveness + readiness probes and a ClusterIP Service. Worker services (automation) receive neither.

**Rationale:** Workers have no HTTP endpoint to probe. Kubernetes restart policy handles crash-loop detection. Liveness probe on a worker would require adding a dummy HTTP server solely for the probe, which is overhead without value.

## 3. broker-gateway PVC strategy

**Decision:** 100Mi ReadWriteOnce PVC mounted at `/app/data/.tokens`.

**Rationale:** Robinhood MFA flow stores session tokens on disk. emptyDir would trigger MFA SMS on every pod restart, breaking login flow and spamming the user. PVC persists tokens across restarts. 100Mi is vastly oversized for token files (actual usage <1 MiB), but PVCs cannot resize down and minimum allocation on most storage classes is 1Gi anyway; 100Mi signals intent.

## 4. Ingress + TLS

**Decision:** Traefik IngressRoute CRD (k3s default controller) + cert-manager Certificate in the chart + ClusterIssuer in `provision-k3s.sh` + edge-nginx in front.

**Rationale:** k3s ships Traefik, so no need to install nginx-ingress. cert-manager handles Let's Encrypt renewal. edge-nginx persists for path-based routing (`/api/`, `/ws/`, `/assets/`), security headers, and the critical 1900s backtest timeout that cannot be set via IngressRoute alone. ClusterIssuer is cluster-scoped and shared across all apps, so it lives outside the Phoenix chart.

## 5. SealedSecret workflow

**Decision:** Template ships as `.yaml.template` with `<SEALED_*>` placeholders. Operator runs `kubeseal --raw` per key, copies ciphertexts into a renamed `.yaml` file, and commits the encrypted result.

**Rationale:** SealedSecret ciphertexts are safe to commit (asymmetric encryption tied to the cluster's controller keypair). The template + manual seal workflow keeps plaintext secrets out of the repo while allowing GitOps on the ciphertext. Helm cannot invoke kubeseal itself (external tooling), so this must be a pre-install step.

## 6. Image strategy

**Decision:** Dual values files. Local dev uses `image: phoenix/<svc>:local` with `pullPolicy: IfNotPresent` (k3s ctr import path). Production uses `ghcr.io/thirunagariharish/phoneixclaw/phoenix-<svc>:{{ .Values.image.tag }}` with `pullPolicy: Always`.

**Rationale:** Local cutover requires zero image pulls (VPS has limited bandwidth). k3s containerd allows pre-importing tars, and IfNotPresent uses the imported image. Production needs latest on every deploy, so Always + tagged GHCR images. The typo "phoneixclaw" is in the actual GitHub repo name and must be preserved.

## 7. Postgres StatefulSet vs operator

**Decision:** Single-replica StatefulSet + 10Gi PVC. No operator (CloudNativePG, Zalando, Crunchy).

**Rationale:** Dataset is 14 MiB. Single-node k3s has no high-availability benefit from an operator. StatefulSet + PVC gives stable Pod identity and durable storage with zero operator overhead. Revisit when multi-node or when dataset exceeds 100 GiB and backup/restore automation becomes critical.
