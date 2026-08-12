#!/usr/bin/env bash
# OPTIONAL: commit + push the SQLite DB snapshots to GitHub on a schedule, so
# the branch keeps a version history / backup of the databases. NOT required
# for the fleet to work — on a persistent host the DBs already persist on local
# disk, and leads are written straight to the Google Sheet regardless of git.
#
# Only enable this if you want the host to be the git writer. If you do, make
# sure NO OTHER process (e.g. the old hourly babysitter session) is also
# pushing to the same branch, or the two will fight over the DB files.
#
# Install as a systemd timer (every 30 min):
#   sudo cp deploy/push-snapshots.sh /usr/local/bin/fire-leadgen-push
#   sudo chmod +x /usr/local/bin/fire-leadgen-push
#   (then create the .service + .timer shown in deploy/README.md)
set -uo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
BRANCH="${BRANCH:-claude/hopeful-newton-izb40o}"
cd "$REPO_DIR" || exit 1

git add -f data/*.sqlite3 2>/dev/null || true
git add -A
if git diff --cached --quiet; then
    exit 0   # nothing changed
fi
git commit -q -m "Update lead database snapshots (persistent host)" || exit 0

for i in 1 2 3 4; do
    if git push origin "$BRANCH"; then exit 0; fi
    sleep $((2 ** i))
done
exit 1
