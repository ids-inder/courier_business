# Courier Outreach

An around-the-clock lead-generation and outreach pipeline for a courier / cargo
business serving **Tricity** (Chandigarh, Mohali, Panchkula) and **Baddi / BBN**.

It finds businesses that dispatch physical goods, sends them a personalised
first email, watches for replies, and — when someone is interested — brings the
booking to **you** to confirm the time before anything lands on a calendar.

> **Design principle:** the machine does the tireless grunt work (finding,
> writing, sending, watching, following up). The human makes the two judgement
> calls that matter: *is this message good* and *do I actually want this
> meeting, at this time*. It never books on your behalf without your say-so.

---

## How it works

```
                        ┌──────────────────────────────────────────────┐
   Small VPS (24/7) ──► │  orchestrator (scheduled loop)               │
                        │                                              │
   1. SOURCE            │  Google Places → discover companies          │
      (find leads)      │  → visit each company's own website          │
                        │  → extract the email they publish            │
                        │            │                                 │
   2. DRAFT + SEND      │  Claude writes a personalised email          │
      (warm-up capped)  │  → SMTP send, within the daily ramp          │
                        │            │                                 │
   3. LISTEN            │  IMAP reads replies (only from people we      │
                        │  emailed) → Claude classifies each           │
                        │            │                                 │
   4. BOOK (human)      │  positive reply → app pings YOU with slots    │
                        │  → you tap one → Google Calendar event +      │
                        │  invite emailed to the lead                   │
                        └──────────────────────────────────────────────┘
        │                                   │
        ▼                                   ▼
   Google Sheet                     Mini web app
   (your cockpit: every            ("Approvals & Chat": the
    lead + status, browse           agent proposes times, you
    on your phone)                  confirm the booking here)
```

- **Source of truth = local SQLite** on the VPS (`courier_outreach.sqlite3`):
  de-duplication, the send log, warm-up accounting, atomic status changes.
- **Cockpit = a Google Sheet**: a human-readable projection of every lead, kept
  in sync so you can eyeball the pipeline from any device.
- **Booking = the mini web app**: your in-app chat, where the agent proposes
  meeting slots and you confirm one.

### The lead lifecycle
`new → queued → sent → (followup_1/2) → replied_positive → meeting_proposed →
meeting_confirmed → booked`, with off-ramps `replied_negative`,
`unsubscribed`, `bounced`, `closed`. Defined in `courier_outreach/models.py`.

---

## Two deliberate design choices (read these)

**1. Sourcing is Google Places + company websites, not directory scraping.**
JustDial / IndiaMART / Sulekha mostly list *phone numbers, not emails*, their
terms forbid automated scraping, and their anti-bot defences make a scraper
brittle and legally risky — with your brand on the outreach. Instead we discover
businesses via Google Places and read the email a company **publishes on its own
website**, which is defensible and actually yields emails. Sourcing is a
pluggable layer (`sourcing/`), so if you have an **IndiaMART/JustDial seller
account**, their *official* lead exports/APIs can be imported cleanly.

**2. Deliverability is throttled on purpose (the warm-up ramp).**
Cold email lands in spam unless you ramp slowly and keep volume low. The
pipeline starts at ~10 emails/day and climbs (`WARMUP_*` in `.env`). This is a
visible knob you control — raise it as reputation builds. Blasting on day one
gets the sender blacklisted and gets you zero meetings; the ramp is *how volume
actually reaches inboxes*.

Because we send **through Gmail** (`inder.traders89@gmail.com`), Google handles
SPF / DKIM / DMARC for `gmail.com` automatically — **no domain and no DNS
records are needed**. The trade-offs: a consumer Gmail address is slightly less
"corporate" to a B2B recipient, and Gmail caps sending at ~**500 emails/day**
(our warm-up max of 40 sits well under). Emails are **preset templates** with
merge fields (`{company}`, `{industry}`, `{area}`) so each one is lightly
personalised rather than obviously bulk.

---

## Privacy

The IMAP reader **only ever processes messages whose sender is a company we
emailed**. Every other message in the mailbox is skipped and never read, stored,
or shown. Your inbox stays yours. (Enforced in the reply-reader against the
leads table; see `models.py` / the mail-in module.)

---

## Setup (once)

1. `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
2. `cp .env.example .env` and fill every value. `.env.example` documents each one.
3. Create a Google **service account**, download its JSON to `credentials/`, and
   share your Sheet + Calendar with the service account's email.
4. Generate a Gmail **App Password** and put it in `SMTP_PASSWORD` / `IMAP_PASSWORD`.

### What you need to provide (the setup checklist)
- [ ] Gmail **App Password** for `inder.traders89@gmail.com` (2-Step Verif. on, IMAP enabled)
- [ ] SSH access to the **VPS** (`deploy@80.241.222.114`)
- [ ] Google **service-account JSON** + the Sheet ID + Calendar ID
- [ ] Lead discovery: a **Places API key** *or* the free OpenStreetMap route
- [ ] **Business details**: name, services, coverage, phone, signature
- [ ] **Booking rules**: days/hours you take meetings, duration, min notice
- [ ] Approve the **email templates** (first-touch + follow-ups)

_No custom domain and no Anthropic key required — Gmail authenticates the mail,
and outreach uses preset templates rather than AI-generated copy._

---

## Project layout

```
courier_outreach/
  __init__.py
  config.py        # all settings, loaded from env (.env in dev)
  models.py        # lead lifecycle, reply classes, Sheet schema
  db.py            # SQLite: leads, messages, send_budget, audit
  sourcing/        # lead discovery (OSM) + website email extraction + CSV import
  templates/       # preset email templates (first-touch + 2 follow-ups)
  mail/            # SMTP sender + warm-up governor; IMAP reply reader
  triage/          # rule-based reply tagging (unsubscribe auto-catch)
  cockpit/         # Google Sheet sync + Calendar booking
  app/             # the "Approvals & Chat" web console (FastAPI)
  orchestrator.py  # the scheduled cycle + CLI (python -m courier_outreach)
deploy/            # systemd units + setup.sh for the VPS
```

## Running it

```bash
python -m courier_outreach init-db   # create the local DB
python -m courier_outreach source    # discover leads (OSM) [+ --csv seeds/leads.csv]
python -m courier_outreach run        # one cycle: read replies -> send due -> sync Sheet
python -m courier_outreach serve      # the Approvals & Chat console (port APP_PORT)
```

On the VPS these are wired to systemd (console always on; cycle every 15 min;
sourcing daily). See `deploy/README.md`.

## Status

All eight slices built and tested: foundation, sourcing, mail out/in, templates
+ triage, Sheet + Calendar, the console app, and the orchestrator + deploy.
Live runs (OSM, SMTP/IMAP, Google) happen on the VPS with real credentials.
