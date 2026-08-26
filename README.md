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
Cold email from a fresh domain lands in spam unless you ramp slowly and keep
volume low and personalised. The pipeline starts at ~10 emails/day and climbs
(`WARMUP_*` in `.env`). This is a visible knob you control — raise it as your
domain's reputation builds. Blasting on day one gets the domain blacklisted and
gets you zero meetings; the ramp is *how volume actually reaches inboxes*.

You will also need **SPF, DKIM, and DMARC** DNS records on your sending domain.
Setup instructions come with the mail module.

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
4. Get an **Anthropic API key** (console.anthropic.com).
5. Point `SMTP_*` / `IMAP_*` at a **dedicated** address (e.g. `sales@…`), not
   your personal inbox.

### What you need to provide (the setup checklist)
- [ ] SMTP + IMAP host / port / user / pass for a dedicated sending address
- [ ] The sending **domain** (so we can spec SPF / DKIM / DMARC)
- [ ] A small **Ubuntu VPS** with SSH access
- [ ] **Anthropic API key**
- [ ] Google **service-account JSON** + the Sheet ID + Calendar ID
- [ ] **Business details**: name, services, coverage, website, phone, signature
- [ ] **Booking rules**: days/hours you take meetings, duration, min notice

---

## Project layout

```
courier_outreach/
  __init__.py
  config.py        # all settings, loaded from env (.env in dev)
  models.py        # lead lifecycle, reply classes, Sheet schema
  db.py            # SQLite: leads, messages, send_budget, audit
  sourcing/        # (next) Places discovery + website email extraction
  mail/            # (next) SMTP sender + warm-up governor; IMAP reply reader
  brain/           # (next) Claude drafting + reply classification
  cockpit/         # (next) Google Sheet + Calendar sync
  app/             # (next) the "Approvals & Chat" web console
  orchestrator.py  # (next) the scheduled loop
```

## Status

Under active construction. Done: foundation (config, data model, SQLite layer,
tested). Next: sourcing → mail → brain → cockpit → app → orchestrator/deploy.
Track progress in the task list.
