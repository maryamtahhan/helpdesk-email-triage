.PHONY: demo up down logs ingest test demo-local

demo:
	podman compose -f compose.demo.yml up --build

up:
	podman compose -f compose.yml up --build -d

down:
	podman compose -f compose.yml down -v || true
	podman compose -f compose.demo.yml down -v || true

logs:
	podman compose -f compose.demo.yml logs -f

ingest:
	./scripts/ingest-sample.sh

test:
	python3 -m pip install -q -r email-gateway/requirements.txt pytest
	PYTHONPATH=email-gateway python3 -m pytest email-gateway/tests -q

demo-local:
	./scripts/run-demo-local.sh
