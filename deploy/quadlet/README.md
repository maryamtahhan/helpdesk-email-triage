# RHEL Quadlet deploy path

Quadlet runs each container as a rootless systemd service on RHEL 9.4+. Use this path instead of `podman compose` when you want containers managed by systemd (auto-restart, journal logging, boot integration).

This is an **enterprise single-host** deploy path. Change default secrets, restrict published ports, and harden vault access before any real production use. Published Quay images (`quay.io/mtahhan/helpdesk-*`) can replace local `podman build` tags in the `.container` files when CI images are available.

## Prerequisites

**Packages:** `podman` from `dnf` (Quadlet included). Compose is **not** required for Quadlet. For `compose.yml` on RHEL 10 only: `sudo dnf install -y python3-pip` and `pip install --user podman-compose`.

**One-time setup** (from repo root):

```bash
podman login registry.redhat.io
# Edit ~/.config/helpdesk/secrets.env if the template was created (real HF token + VAULT_SECRET)
vi ~/.config/helpdesk/secrets.env

make quadlet-setup quadlet-build
make quadlet-up
```

`make quadlet-up` starts **network → inference → waits for `/v1/models` → gateway + UI**, then copies sample `.eml` files only after `/health/ready` (avoids `heuristic-fallback` on cold start). Skip auto-ingest: `SKIP_INGEST=1 make quadlet-up`. Enable linger on boot: `ENABLE_LINGER=1 make quadlet-up`.

Manual equivalent (no Make):

```bash
mkdir -p ~/.config/containers/systemd ~/.config/helpdesk \
  ~/helpdesk/sample_emails ~/helpdesk/docs ~/rhaii-cache

cat > ~/.config/helpdesk/secrets.env <<'EOF'
HUGGING_FACE_HUB_TOKEN=hf_your_token_here
VAULT_SECRET=change-me-before-deploy
EOF
chmod 600 ~/.config/helpdesk/secrets.env

cp -r sample_emails/. ~/helpdesk/sample_emails/
cp -r docs/. ~/helpdesk/docs/

podman build -f email-gateway/Containerfile -t localhost/helpdesk-email-gateway:prod .
podman build -f agent-dashboard/Containerfile -t localhost/helpdesk-triage-ui:prod .
cp deploy/quadlet/*.container deploy/quadlet/*.network deploy/quadlet/*.volume \
   ~/.config/containers/systemd/
systemctl --user daemon-reload
systemctl --user start helpdesk-network.service gateway-data-volume.service
systemctl --user start rhaii-cpu-engine.service
until curl -sf http://127.0.0.1:8000/v1/models >/dev/null; do sleep 15; done
systemctl --user start email-gateway.service agent-dashboard.service
```

## Makefile targets

| Target | Purpose |
|--------|---------|
| `make quadlet-setup` | Dirs, copy Quadlet units + samples/docs, create `secrets.env` only if missing |
| `make quadlet-build` | Build `localhost/helpdesk-*:prod` images |
| `make quadlet-up` | Ordered start + wait for inference + ingest samples |
| `make quadlet-verify` | Status, health, ticket models |
| `make quadlet-ingest` | Re-copy samples after stack is ready |
| `make quadlet-down` | Stop services (keep data) |
| `make quadlet-reset` | Full teardown (`QUADLET_RESET_CONFIRM=1`; optional `WIPE_RHAII_CACHE=1`) |
| `make quadlet-deploy` | `setup` + `build` + `up` |
| `make quadlet-relaunch` | `quadlet-reset` + `quadlet-deploy` (`QUADLET_RESET_CONFIRM=1`) |

Increase inference wait: `RHAII_WAIT_TIMEOUT=1200 make quadlet-up`.

## Verify

```bash
systemctl --user status rhaii-cpu-engine email-gateway agent-dashboard
podman ps
curl -sS http://127.0.0.1:8080/health
curl -sS http://127.0.0.1:8080/tickets | python3 -m json.tool | head -20
curl -sI http://127.0.0.1:8501/welcome | head -5
```

Open: [http://127.0.0.1:8501/welcome](http://127.0.0.1:8501/welcome)

### Logs

```bash
podman logs -f rhaii-cpu-engine
podman logs -f rhaii-email-gateway
podman logs -f rhaii-triage-ui
```

If `journalctl --user` reports **No journal files were found**, use `podman logs` above, or run `sudo loginctl enable-linger "$USER"`, reconnect SSH, then `journalctl --user -u rhaii-cpu-engine.service -f`.

### `rhaii-cpu-engine` crash-loops (`status=1/FAILURE`)

```bash
podman logs rhaii-cpu-engine --tail 80
```

| Symptom | Fix |
|---|---|
| Hugging Face / 401 / gated model | Set a valid `HUGGING_FACE_HUB_TOKEN` in `~/.config/helpdesk/secrets.env` (accept the model license on huggingface.co) |
| `registry.redhat.io` pull errors | `podman login registry.redhat.io` |
| OOM / cannot allocate | Use a host with **≥16 GiB RAM** (32 GiB recommended for RHAII CPU). Lower `VLLM_CPU_KVCACHE_SPACE` in `rhaii-cpu-engine.container` only on tight hosts |
| Process exits in ~10s | Re-copy `rhaii-cpu-engine.container` from the repo (needs `LD_PRELOAD` + `--port 8000`), then `systemctl --user daemon-reload && systemctl --user restart rhaii-cpu-engine` |

Gateway `/health` may show `"classify_model":""` while inference is down — fix `rhaii-cpu-engine` first, then `systemctl --user restart email-gateway`.

Optional ingest:

```bash
./scripts/ingest-sample.sh
```

## Check status

```bash
systemctl --user status rhaii-cpu-engine email-gateway agent-dashboard
podman logs -f rhaii-cpu-engine
```

## Stop and remove

```bash
make quadlet-down
QUADLET_RESET_CONFIRM=1 make quadlet-reset   # full clean slate; then quadlet-setup + quadlet-build + quadlet-up
```

## Changing the model

To use `Qwen/Qwen2.5-7B-Instruct` on a larger host, edit `rhaii-cpu-engine.container`:

```ini
Exec=--model Qwen/Qwen2.5-7B-Instruct --host 0.0.0.0
Environment=VLLM_CPU_KVCACHE_SPACE=20
```

Then reload: `systemctl --user daemon-reload && systemctl --user restart rhaii-cpu-engine`
