#!/usr/bin/env bash
# Supervisor wrapper: keeps `fire-leadgen run-all` alive across stalls.
#
# The run-all process has an internal stall watchdog that os._exit(1)s if no
# sector makes progress for ~20 min (a hung network call freezing every
# thread). This loop restarts it automatically instead of waiting for the
# hourly babysit kick. A clean exit (code 0, e.g. SIGTERM shutdown) stops the
# loop so operators can still take it down deliberately.
#
# Singleton: a second wrapper cannot start while one holds the flock on
# data/.run-forever.lock, so a stray relaunch (e.g. an hourly babysit racing
# the wrapper's own 5s restart gap) exits immediately instead of stacking a
# duplicate supervisor. We deliberately DO NOT rm data/*.lock: flock is
# released by the kernel when a holder dies, so a leftover file from a dead
# run-all does not block the next one, and removing files mid-run would let a
# duplicate run-all acquire fresh locks and double-process sectors.
set -u
cd "$(dirname "$0")/.." || exit 1

BIN=".venv/bin/fire-leadgen"
LOG="data/agent.log"
LOCK="data/.run-forever.lock"

mkdir -p data
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "$(date -u +%H:%M:%S) run-forever: another wrapper already running - exiting" >> "$LOG"
    exit 0
fi

while true; do
    echo "$(date -u +%H:%M:%S) run-forever: (re)starting run-all" >> "$LOG"
    "$BIN" run-all >> "$LOG" 2>&1
    code=$?
    if [ "$code" -eq 0 ]; then
        echo "$(date -u +%H:%M:%S) run-forever: run-all exited cleanly (0) - stopping" >> "$LOG"
        break
    fi
    echo "$(date -u +%H:%M:%S) run-forever: run-all exited $code - restarting in 5s" >> "$LOG"
    sleep 5
done
