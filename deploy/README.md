# Deploying on the VPS (`deploy@80.241.222.114`)

Runs the pipeline around the clock: a **console** service (always on) plus two
**timers** — a cycle every 15 min (read replies → send due → sync Sheet) and a
daily sourcing run.

## Prerequisites
- Ubuntu/Debian with `python3` (3.11+) and `git`.
- The `deploy` user with `sudo` (needed only to install the systemd units).

## 1. Get the code onto the server
This is a **private** repo, so the server needs read access. Easiest options:
- **Deploy key:** create an SSH key on the server (`ssh-keygen -t ed25519`), add
  the public key to the repo's *Settings → Deploy keys* (read-only), then clone
  via SSH; or
- **Copy it up:** from your machine, `scp -r courier_business deploy@80.241.222.114:~/`.

Then run the setup script:
```bash
ssh deploy@80.241.222.114
bash ~/courier_business/deploy/setup.sh
```
It creates the venv, installs dependencies, makes `.env` from the template, and
initialises the database.

## 2. Configure secrets
```bash
cd ~/courier_business
nano .env
```
Fill in:
- `SMTP_PASSWORD` / `IMAP_PASSWORD` — your Gmail **App Password** (16 chars).
- `APP_ACCESS_TOKEN` — a long random string; this is your console login.
- `GOOGLE_SHEET_ID`, `GOOGLE_CALENDAR_ID` (`inder.traders89@gmail.com`).

Put the Google service-account JSON at
`credentials/google_service_account.json`, and share the Sheet + Calendar with
the service account's email (see the main README).

## 3. Install and start the services
```bash
sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now courier-console.service
sudo systemctl enable --now courier-cycle.timer
sudo systemctl enable --now courier-source.timer
```

Open the console at **http://80.241.222.114:8080** and sign in with your
`APP_ACCESS_TOKEN`.

## 4. Verify
```bash
systemctl status courier-console.service
systemctl list-timers | grep courier
journalctl -u courier-cycle.service -n 50 --no-pager
# run steps by hand:
./.venv/bin/python -m courier_outreach source   # find leads now
./.venv/bin/python -m courier_outreach send     # send a batch now (within caps)
./.venv/bin/python -m courier_outreach sync      # push to the Sheet now
```

## Updating later
```bash
cd ~/courier_business && git pull
./.venv/bin/pip install -r requirements.txt
sudo systemctl restart courier-console.service
```

## Security notes
- The console is protected by the token but served over plain HTTP. Lock the
  port to your own IP with a firewall, e.g.:
  `sudo ufw allow from <your-ip> to any port 8080` (and deny others), or put it
  behind a reverse proxy (Caddy/nginx) with HTTPS.
- Keep `.env` and `credentials/` private — both are git-ignored.
- Start conservative: the warm-up ramp begins at ~10 emails/day. Raise
  `WARMUP_*` in `.env` only as your Gmail reputation builds.
