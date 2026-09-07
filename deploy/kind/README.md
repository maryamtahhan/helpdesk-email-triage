# Kind (Kubernetes in Docker) testing

Plain Kubernetes manifests for CI and local testing without OpenShift Routes or RBAC.

## Layout

```
deploy/kind/
├── kind-config.yaml              # Single-node kind cluster
└── overlays/mock-demo/           # Mock inference + gateway + dashboard
```

Reuses `deploy/openshift/base/` but omits Routes, route-reader RBAC, and pulls local `:ci` images with `imagePullPolicy: Never`.

## Deploy and verify

```bash
make kind-e2e
```

The script builds images, loads them into kind, applies manifests, waits for pods, port-forwards the gateway, and verifies:

- `GET /health` → `{"status":"ok"}`
- `POST /ingest` via `./scripts/ingest-sample.sh`
- at least one ticket on `GET /tickets`

## Manual verify (keep cluster)

```bash
KEEP_CLUSTER=1 make kind-e2e

kubectl get pods,svc -n helpdesk-kind-test
kubectl port-forward -n helpdesk-kind-test svc/email-gateway 8080:8080 &
curl -sS http://127.0.0.1:8080/health
./scripts/ingest-sample.sh
curl -sS http://127.0.0.1:8080/tickets | python3 -m json.tool | head -20

kubectl port-forward -n helpdesk-kind-test svc/agent-dashboard 8501:8501 &
# Open: http://127.0.0.1:8501
```

## Cleanup

The script deletes the kind cluster on exit unless `KEEP_CLUSTER=1`.

```bash
kind delete cluster --name helpdesk-ci
```

## CI

GitHub Actions job `kind-e2e` in `.github/workflows/ci.yml` runs `make kind-e2e` on every PR.
