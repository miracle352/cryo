#!/usr/bin/env bash
# Start a Claude Code agent under cryo and hand it a long task that ends with
# an email report sent through the Sprites Resend connector.
#
#   ./demo/overnight.sh            # default task: audit cryo itself
#   ./demo/overnight.sh "your task"
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
work=/home/sprite/overnight
mkdir -p "$work"
cp "$here/demo/CLAUDE.md" "$work/CLAUDE.md"
ln -sf "$here/cryo" /usr/local/bin/cryo 2>/dev/null || sudo ln -sf "$here/cryo" /usr/local/bin/cryo

task=${1:-"Read $here/cryo and $here/README.md. Find real bugs or risky edge cases in how cryo freezes and thaws processes. Write REPORT.md in this folder: a short summary, then each issue with the line, why it matters and a suggested fix. Then email REPORT.md to me with cryo report --subject 'Overnight agent: cryo audit' --file REPORT.md. Work carefully; the machine may restart while you work."}

# Claude Code asks "do you trust this folder?" the first time it opens one, and
# the answer defaults to No. Nobody is there to answer overnight, so say yes for
# this folder up front (it's ours, made above).
sudo env HOME=/home/sprite python3 - "$work" <<'PY'
import json, os, sys
p = os.path.expanduser("~/.claude.json")
try:
    c = json.load(open(p))
except (OSError, ValueError):
    c = {}
c.setdefault("projects", {}).setdefault(sys.argv[1], {})["hasTrustDialogAccepted"] = True
json.dump(c, open(p, "w"), indent=2)
PY

# start clean: park any old copy so cryo doesn't thaw it while we replace it
sudo "$here/cryo" stop overnight 2>/dev/null || true
sudo tmux -L cryo-overnight kill-server 2>/dev/null || true
sudo env PATH="$PATH" HOME=/home/sprite IS_SANDBOX=1 "$here/cryo" run overnight --tmux --cwd "$work" -- claude --dangerously-skip-permissions
sleep 12
sudo "$here/cryo" say overnight "$task"
echo
echo "overnight agent started. watch it:   sudo cryo peek overnight"
echo "restart the sprite any time; cryo brings it back and it keeps going."
