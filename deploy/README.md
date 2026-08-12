# Running the lead-gen fleet on a persistent host

This turns the multi-sector agent into a 24/7 service on a normal always-on
machine, instead of the ephemeral session container that gets reclaimed every
hour. That single change is what lets the ~31k-company backlog actually drain
(the fleet keeps processing around the clock) and removes the hourly
"restart the dead supervisor" babysitting.

Any small Linux box works: a $5–10/mo cloud VM (DigitalOcean / Hetzner / Linode /
EC2 t3.micro), or a server you already own. 1 vCPU / 1 GB RAM is plenty.

## Why a real host is faster (not just always-on)

- **Uptime:** runs continuously instead of a few minutes per hour.
- **Direct internet:** a normal host talks straight to Serper/Hunter/Google,
  instead of the flaky agent proxy that drops connections (the `os error 111`
  export failures). Per-company processing is faster and far more reliable.

## One-time setup (≈10 minutes)

On a fresh Ubuntu 22.04+/Debian 12+ box, as a normal user with `sudo`:

```bash
# 1. Clone the branch that carries the databases + configs
git clone -b claude/hopeful-newton-izb40o \
    https://github.com/clewpartnersny/Fire-lead-gen-agent.git
cd Fire-lead-gen-agent

# 2. Provision: installs python venv, the package, and the systemd service
bash deploy/setup.sh

# 3. Create the .env (the setup script prints this template). Fill in the real
#    keys — this file is gitignored, keep it off GitHub:
nano .env

# 4. Start it, and have it come back on every reboot (enable was done in setup)
sudo systemctl start fire-leadgen
```

That's it. Verify:

```bash
systemctl status fire-leadgen          # should say "active (running)"
tail -f data/agent.log                 # watch cycles: "[Fire Protection] Cycle done…"
```

## Operating it

| Action | Command |
|---|---|
| Live logs | `journalctl -u fire-leadgen -f` or `tail -f data/agent.log` |
| Status | `systemctl status fire-leadgen` |
| Stop | `sudo systemctl stop fire-leadgen` |
| Restart | `sudo systemctl restart fire-leadgen` |
| After editing a sector's `config.yaml` | `sudo systemctl restart fire-leadgen` |

`Restart=always` in the unit means if the process ever crashes (or the internal
stall-watchdog force-exits on a wedged network call) systemd brings it right
back within 5 seconds. No wrapper script needed.

## Databases & the Google Sheet

- Leads are written **straight to your Google Sheet** via the webhook, exactly
  as today — that does not depend on git at all.
- The SQLite DBs live on the host's local disk and persist across restarts, so
  no data is lost between runs.
- Committing DB snapshots back to GitHub is **optional** (see
  `push-snapshots.sh`). Only turn it on if you want the host to be the git
  writer — and if you do, stop the old hourly-babysitter session first so two
  processes aren't pushing to the same branch and fighting over the DB files.

### Optional: periodic DB backup to GitHub

Needs a git credential on the box with push access (a GitHub
[fine-grained PAT](https://github.com/settings/tokens) scoped to this repo, or a
deploy key). Then:

```bash
sudo cp deploy/push-snapshots.sh /usr/local/bin/fire-leadgen-push
sudo chmod +x /usr/local/bin/fire-leadgen-push

sudo tee /etc/systemd/system/fire-leadgen-push.service >/dev/null <<'EOF'
[Unit]
Description=Push lead DB snapshots to GitHub
[Service]
Type=oneshot
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/Fire-lead-gen-agent
ExecStart=/usr/local/bin/fire-leadgen-push
EOF

sudo tee /etc/systemd/system/fire-leadgen-push.timer >/dev/null <<'EOF'
[Unit]
Description=Push lead DB snapshots every 30 min
[Timer]
OnBootSec=10min
OnUnitActiveSec=30min
[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now fire-leadgen-push.timer
```

## After it's running: rebalance throughput

While stuck on the ephemeral container, discovery was throttled and 9 sectors
were paced down to prioritise Fire (uptime was the bottleneck). On a persistent
host that constraint is gone — you can turn everything back up to full speed.
Ask the agent to "reset the sector configs to balanced high-throughput now that
we're on a persistent host," or edit each `sectors/<slug>/config.yaml`:

```yaml
scheduler:
  cycle_delay_seconds: 60
  queries_per_cycle: 10          # discovery back on (once Serper has credits)
  request_delay_seconds: 1
  max_companies_per_cycle: 100
```

then `sudo systemctl restart fire-leadgen`.
