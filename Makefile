.PHONY: demo up down logs ingest test lint demo-local gateway-only test-webhook webhook-receiver \
        validate-manifests compose-e2e build-images deploy-openshift verify-openshift \
        undeploy-openshift run-on-kind destroy-kind kind-e2e

# demo          — mock inference + gateway + Streamlit UI
# gateway-only  — mock inference + gateway (integrator path, no UI)
# ingest        — POST sample_emails/01-billing-double-charge.eml
# test          — unit tests (email-gateway/tests)
# test-webhook  — self-contained TICKET_SINK e2e (no compose)
# webhook-receiver — local webhook listener for manual testing

demo:
	podman compose -f compose.mock.demo.yml up --build

gateway-only:
	podman compose -f compose.gateway-only.yml up --build

up:
	podman compose -f compose.yml up --build -d

down:
	podman compose -f compose.yml down -v || true
	podman compose -f compose.mock.demo.yml down -v || true
	podman compose -f compose.gateway-only.yml down -v || true

logs:
	podman compose -f compose.mock.demo.yml logs -f

ingest:
	./scripts/ingest-sample.sh

test:
	test -d .venv || python3 -m venv .venv
	.venv/bin/pip install -q -r email-gateway/requirements.txt pytest
	PYTHONPATH=email-gateway .venv/bin/python -m pytest email-gateway/tests -q

lint:
	test -d .venv || python3 -m venv .venv
	.venv/bin/pip install -q ruff
	.venv/bin/ruff check email-gateway agent-dashboard inference-mock

demo-local:
	./scripts/run-demo-local.sh

test-webhook:
	chmod +x scripts/test-webhook-sink.sh scripts/webhook-receiver.py
	./scripts/test-webhook-sink.sh

webhook-receiver:
	chmod +x scripts/webhook-receiver.py
	./scripts/webhook-receiver.py --secret $${TICKET_SINK_SECRET:-demo-secret}

validate-manifests:
	chmod +x scripts/validate-openshift-manifests.sh
	./scripts/validate-openshift-manifests.sh

compose-e2e:
	chmod +x scripts/compose-e2e.sh scripts/wait-for-tickets.sh
	./scripts/compose-e2e.sh

build-images:
	podman build -f email-gateway/Containerfile -t localhost/helpdesk-email-gateway:local .
	podman build -f agent-dashboard/Containerfile -t localhost/helpdesk-triage-ui:local .
	podman build -f inference-mock/Containerfile -t localhost/helpdesk-inference-mock:local ./inference-mock

deploy-openshift:
	chmod +x scripts/deploy-openshift.sh scripts/openshift-rhaii-secrets.sh scripts/openshift-verify.sh
	./scripts/deploy-openshift.sh

verify-openshift:
	chmod +x scripts/openshift-verify.sh
	./scripts/openshift-verify.sh

undeploy-openshift:
	chmod +x scripts/undeploy-openshift.sh
	./scripts/undeploy-openshift.sh

run-on-kind:
	chmod +x scripts/run-on-kind.sh scripts/kind-lib.sh
	./scripts/run-on-kind.sh

destroy-kind:
	chmod +x scripts/destroy-kind.sh
	./scripts/destroy-kind.sh

kind-e2e:
	chmod +x scripts/kind-e2e.sh scripts/kind-lib.sh scripts/destroy-kind.sh scripts/wait-for-tickets.sh
	./scripts/kind-e2e.sh
