#!/usr/bin/env bash
# One-shot provisioner for running the multi-sector lead-gen fleet 24/7 on a
# persistent Ubuntu/Debian host (VM, VPS, or bare metal). Idempotent: safe to
# re-run. Run as a normal user WITH sudo available (it uses sudo only for the
# apt install and the systemd unit).
#
#   git clone -b claude/hopeful-newton-izb40o \
#       https://github.com/clewpartnersny/Fire-lead-gen-agent.git
#   cd Fire-lead-gen-agent
#   bash deploy/setup.sh
#
# After it finishes, create data/.env (the script prints the template) and then:
#   sudo systemctl start fire-leadgen
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_USER="${SUDO_USER:-$(id -un)}"
BRANCH="${BRANCH:-claude/hopeful-newton-izb40o}"

echo "==> Repo:    $REPO_DIR"
echo "==> User:    $SERVICE_USER"
echo "==> Branch:  $BRANCH"

# 1. System dependencies -----------------------------------------------------
if command -v apt-get >/dev/null 2>&1; then
    echo "==> Installing system packages (python3-venv, git)…"
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-venv python3-pip git
fi

# 2. Python venv + package ---------------------------------------------------
cd "$REPO_DIR"
if [ ! -x ".venv/bin/python" ]; then
    echo "==> Creating virtualenv…"
    python3 -m venv .venv
fi
echo "==> Installing the fire-leadgen package…"
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -e .

mkdir -p data

# 3. .env check --------------------------------------------------------------
if [ ! -f ".env" ]; then
    echo ""
    echo "!!  data/.env is MISSING. Create $REPO_DIR/.env with this content"
    echo "!!  (fill in your real keys — do NOT commit this file):"
    echo "--------------------------------------------------------------------"
    cat <<'ENVTMPL'
HUNTER_API_KEY=<your-hunter-key>
ROCKETREACH_API_KEY=<your-rocketreach-key>
SERPER_API_KEY=<your-serper-key>
GOOGLE_SHEET_ID=<your-sheet-id>
GOOGLE_SHEET_WORKSHEET=Sheet1
SHEETS_WEBHOOK_URL=<your-apps-script-exec-url>
SHEETS_WEBHOOK_SECRET=<your-webhook-secret>
ENVTMPL
    echo "--------------------------------------------------------------------"
    ENV_MISSING=1
else
    echo "==> .env present."
    ENV_MISSING=0
fi

# 4. systemd service ---------------------------------------------------------
echo "==> Installing systemd unit fire-leadgen.service…"
sudo tee /etc/systemd/system/fire-leadgen.service >/dev/null <<UNIT
[Unit]
Description=Fire multi-sector lead-gen fleet (run-all)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$REPO_DIR
ExecStart=$REPO_DIR/.venv/bin/fire-leadgen run-all
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
# Direct internet on a real host — no agent proxy needed.
StandardOutput=append:$REPO_DIR/data/agent.log
StandardError=append:$REPO_DIR/data/agent.log

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable fire-leadgen >/dev/null 2>&1 || true

echo ""
echo "===================================================================="
echo "Setup complete."
if [ "${ENV_MISSING:-0}" = "1" ]; then
    echo "  1. Create the .env file shown above."
    echo "  2. Start it:   sudo systemctl start fire-leadgen"
else
    echo "  Start it:      sudo systemctl start fire-leadgen"
fi
echo "  Watch logs:    journalctl -u fire-leadgen -f   (or tail -f data/agent.log)"
echo "  Status:        systemctl status fire-leadgen"
echo "  Stop:          sudo systemctl stop fire-leadgen"
echo "===================================================================="
