.PHONY: demo up down logs ingest test demo-local gateway-only test-webhook webhook-receiver

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

demo-local:
	./scripts/run-demo-local.sh

test-webhook:
	chmod +x scripts/test-webhook-sink.sh scripts/webhook-receiver.py
	./scripts/test-webhook-sink.sh

webhook-receiver:
	chmod +x scripts/webhook-receiver.py
	./scripts/webhook-receiver.py --secret $${TICKET_SINK_SECRET:-demo-secret}
