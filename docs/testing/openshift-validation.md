# OpenShift validation

Checks that require an OpenShift cluster and (for RHAII paths) `registry.redhat.io` plus a Hugging Face token.

## Deploy and smoke test

```bash
INFERENCE=rhaii make deploy-openshift   # or INFERENCE=mock for mock-only
make verify-openshift
```

`verify-openshift` prints Route URLs and runs health / ticket checks. Details: [deploy-openshift.md](../deploy-openshift.md).

## GuideLLM (inference benchmarking)

**Canonical steps:** [README → Load testing](../README.md#load-testing) (`make guidellm-openshift` on OpenShift, `make guidellm-quadlet` on RHEL Quadlet). Use that section for image names, env vars, and reading HTML/JSON reports.

This folder covers **functional** OpenShift checks (`verify-openshift`), not pilot sizing benchmarks.

## Gateway load (not GuideLLM)

GuideLLM targets **inference** only. For parallel **gateway** ingest, use multiple `POST /ingest/raw` against the gateway Route; add `X-Ingest-Key` when hardened. See README [Load testing](../README.md#load-testing).

## Tear-down

```bash
make undeploy-openshift
# DELETE_NAMESPACE=1 make undeploy-openshift
```
