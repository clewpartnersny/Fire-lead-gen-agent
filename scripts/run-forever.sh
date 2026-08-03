#!/usr/bin/env bash
# Supervisor wrapper: keeps `fire-leadgen run-all` alive across stalls.
#
# The run-all process has an internal stall watchdog that os._exit(1)s if no
# sector makes progress for ~20 min (a hung network call freezing every
# thread). This loop restarts it automatically instead of waiting for the
# hourly babysit kick. A clean exit (code 0, e.g. SIGTERM shutdown) stops the
# loop so operators can still take it down deliberately.
set -u
cd "$(dirname "$0")/.." || exit 1

BIN=".venv/bin/fire-leadgen"
LOG="data/agent.log"

while true; do
    echo "$(date -u +%H:%M:%S) run-forever: (re)starting run-all" >> "$LOG"
    rm -f data/*.lock
    "$BIN" run-all >> "$LOG" 2>&1
    code=$?
    if [ "$code" -eq 0 ]; then
        echo "$(date -u +%H:%M:%S) run-forever: run-all exited cleanly (0) - stopping" >> "$LOG"
        break
    fi
    echo "$(date -u +%H:%M:%S) run-forever: run-all exited $code - restarting in 5s" >> "$LOG"
    sleep 5
done
