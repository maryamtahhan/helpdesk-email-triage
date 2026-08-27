# Podman Quadlet deployment

Quadlet runs each container as a rootless systemd service. This is the recommended production deployment on RHEL 9.4+ instead of `podman compose`.

## Prerequisites

```bash
# 1. Authenticate with the Red Hat registry
podman login registry.redhat.io

# 2. Create the model cache directory
mkdir -p ~/rhaii-cache

# 3. Store secrets (Hugging Face token + vault auth secret)
mkdir -p ~/.config/helpdesk
cat > ~/.config/helpdesk/secrets.env <<'EOF'
HF_TOKEN=hf_your_token_here
VAULT_SECRET=change-me-before-deploy
EOF
chmod 600 ~/.config/helpdesk/secrets.env

# 4. Copy sample emails to the watched directory
mkdir -p ~/helpdesk/sample_emails ~/helpdesk/docs
cp -r sample_emails/. ~/helpdesk/sample_emails/
cp -r docs/. ~/helpdesk/docs/

# 5. Build the application images
podman build -t localhost/helpdesk-email-gateway:prod ./email-gateway
podman build -t localhost/helpdesk-triage-ui:prod ./agent-dashboard
```

## Install and start

```bash
# Copy unit files to the Quadlet directory
cp deploy/quadlet/*.container deploy/quadlet/*.network deploy/quadlet/*.volume \
   ~/.config/containers/systemd/

# Reload systemd and start the stack
systemctl --user daemon-reload
systemctl --user enable --now rhaii-cpu-engine.service email-gateway.service agent-dashboard.service
```

## Check status

```bash
systemctl --user status rhaii-cpu-engine email-gateway agent-dashboard
journalctl --user -u rhaii-cpu-engine -f
```

## Stop and remove

```bash
systemctl --user stop agent-dashboard email-gateway rhaii-cpu-engine
systemctl --user disable agent-dashboard email-gateway rhaii-cpu-engine
```

## Changing the model

To use `Qwen/Qwen2.5-7B-Instruct` on a larger host, edit `rhaii-cpu-engine.container`:

```ini
Exec=--model Qwen/Qwen2.5-7B-Instruct --host 0.0.0.0
Environment=VLLM_CPU_KVCACHE_SPACE=20
```

Then reload: `systemctl --user daemon-reload && systemctl --user restart rhaii-cpu-engine`
