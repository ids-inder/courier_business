#!/usr/bin/env bash
# One-shot setup for the courier outreach pipeline on the VPS (run as user `deploy`).
# Usage:  bash deploy/setup.sh [branch]
set -euo pipefail

REPO="https://github.com/ids-inder/courier_business.git"
DIR="/home/deploy/courier_business"
BRANCH="${1:-claude/courier-outreach-agents-matcgt}"

echo "==> Installing to $DIR (branch: $BRANCH)"

# 1. Clone or update the code
if [ ! -d "$DIR/.git" ]; then
  git clone "$REPO" "$DIR"
fi
cd "$DIR"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull origin "$BRANCH"

# 2. Python venv + dependencies
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

# 3. Config + credentials scaffolding
mkdir -p credentials seeds
if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> Created .env from template — you must edit it (next steps)."
fi

# 4. Initialise the local database
./.venv/bin/python -m courier_outreach init-db

cat <<'NEXT'

==> Setup complete. Now finish configuration:

  1) Edit secrets:            nano .env
       - SMTP_PASSWORD / IMAP_PASSWORD  = your Gmail 16-char App Password
       - APP_ACCESS_TOKEN               = a long random string (your console login)
       - GOOGLE_SHEET_ID / GOOGLE_CALENDAR_ID
  2) Add the Google key:      place the service-account JSON at
                              credentials/google_service_account.json
  3) Install the services (needs sudo):
       sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/
       sudo systemctl daemon-reload
       sudo systemctl enable --now courier-console.service
       sudo systemctl enable --now courier-cycle.timer
       sudo systemctl enable --now courier-source.timer
  4) Open the console:        http://<this-server-ip>:8080

Handy checks:
  systemctl status courier-console.service
  journalctl -u courier-cycle.service -n 50 --no-pager
  ./.venv/bin/python -m courier_outreach source   # discover leads now
  ./.venv/bin/python -m courier_outreach send     # send a batch now (within caps)
NEXT
