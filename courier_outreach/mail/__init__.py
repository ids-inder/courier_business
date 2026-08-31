"""Mail: sending outreach (SMTP) and reading replies (IMAP).

- sender.py   — build + send a message over Gmail SMTP.
- governor.py — the warm-up ramp + send-window gate (deliverability protection).
- reader.py   — (next) IMAP reply reader, restricted to known senders.
"""
