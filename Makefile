.PHONY: demo up down logs ingest test demo-local

demo:
	podman compose -f compose.mock.demo.yml up --build

up:
	podman compose -f compose.yml up --build -d

down:
	podman compose -f compose.yml down -v || true
	podman compose -f compose.mock.demo.yml down -v || true

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
