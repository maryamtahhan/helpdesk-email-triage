# Kind (Kubernetes in Docker) testing

Plain Kubernetes manifests for CI and local testing without OpenShift Routes or RBAC.

## Layout

```
deploy/kind/
├── kind-config.yaml              # Single-node kind cluster
└── overlays/mock-demo/           # Mock inference + gateway + dashboard
```

Reuses `deploy/openshift/base/` but omits Routes, route-reader RBAC, and pulls local `:ci` images with `imagePullPolicy: Never`.

## Run locally (keep cluster)

```bash
make run-on-kind
```

Creates a kind cluster (or reuses `helpdesk-ci`), builds images, loads them, applies the mock stack, and prints port-forward + verify commands.

Recreate the cluster from scratch:

```bash
RECREATE_CLUSTER=1 make run-on-kind
```

## Verify

In separate terminals (after `make run-on-kind`):

```bash
kubectl port-forward -n helpdesk-kind-test svc/email-gateway 8080:8080 3025:3025
kubectl port-forward -n helpdesk-kind-test svc/agent-dashboard 8501:8501
```

```bash
curl -sS http://127.0.0.1:8080/health
./scripts/ingest-sample.sh
curl -sS http://127.0.0.1:8080/tickets | python3 -m json.tool | head -20
curl -sI http://127.0.0.1:8501 | head -5
```

Open: [http://127.0.0.1:8501](http://127.0.0.1:8501)

## Teardown

```bash
make destroy-kind
# or: kind delete cluster --name helpdesk-ci
```

## CI smoke test

```bash
make kind-e2e
```

Builds, deploys, verifies health → ingest → ticket, then runs `destroy-kind` automatically.

## CI

GitHub Actions job `kind-e2e` in `.github/workflows/ci.yml` runs `make kind-e2e` on every PR.
