"""The Approvals & Chat console (FastAPI).

One screen: replies that need your decision appear as chat cards; each positive
one offers in-person slots — click one and it books (Calendar + confirmation
email). Protected by a shared token cookie (APP_ACCESS_TOKEN).

`create_app(deps)` takes its dependencies so tests can inject a temp DB and a
fake booker (no live Google needed).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Template

from .. import db
from ..config import Config, SmtpConfig
from ..cockpit.calendar import book_meeting
from ..models import LeadStatus
from .slots import propose_slots

log = logging.getLogger(__name__)


@dataclass
class AppDeps:
    config: Config
    smtp_config: SmtpConfig | None
    db_path: Path
    booker: Callable = field(default=book_meeting)

    def connect(self):
        return db.connect(self.db_path)

    def now(self) -> datetime:
        try:
            return datetime.now(ZoneInfo(self.config.booking.timezone)).replace(tzinfo=None)
        except Exception:
            return datetime.now()


_ACTIONABLE = (LeadStatus.REPLIED_POSITIVE.value, LeadStatus.REPLIED_QUESTION.value)

DASHBOARD = Template("""
<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Deep Cargo Movers — Outreach</title>
<style>
 body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f4f6f8;color:#1a2733}
 header{background:#0f3d5e;color:#fff;padding:14px 18px;font-weight:600;font-size:18px}
 .wrap{max-width:760px;margin:0 auto;padding:16px}
 .msg{background:#e7f6ec;border:1px solid #b7e0c4;padding:8px 12px;border-radius:8px;margin-bottom:14px}
 .stats{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px}
 .stat{background:#fff;border:1px solid #dce3e9;border-radius:8px;padding:8px 12px;font-size:13px}
 .stat b{display:block;font-size:18px}
 h2{font-size:15px;text-transform:uppercase;letter-spacing:.04em;color:#5b6b7a;margin:18px 0 8px}
 .card{background:#fff;border:1px solid #dce3e9;border-radius:10px;padding:14px;margin-bottom:14px}
 .co{font-weight:600;font-size:16px}
 .meta{color:#5b6b7a;font-size:13px;margin-bottom:8px}
 .bubble{background:#eef2f6;border-radius:10px;padding:10px 12px;margin:8px 0;white-space:pre-wrap}
 .agent{color:#0f3d5e;font-weight:600;margin-top:10px}
 .slots{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
 button{font:inherit;cursor:pointer;border-radius:8px;border:1px solid #0f3d5e;background:#0f3d5e;color:#fff;padding:8px 12px}
 button.ghost{background:#fff;color:#334}
 form{display:inline}
 .tag{font-size:12px;padding:2px 8px;border-radius:20px;background:#fdeab7;color:#7a5b00;margin-left:6px}
 .row{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
 .booked{color:#0a6b2e;font-weight:600}
 input[type=datetime-local]{font:inherit;padding:6px;border:1px solid #ccd;border-radius:6px}
 a.logout{color:#cfe3ef;float:right;font-weight:400;font-size:13px;text-decoration:none}
</style></head><body>
<header>Deep Cargo Movers — Outreach <a class="logout" href="/logout">log out</a></header>
<div class="wrap">
 {% if msg %}<div class="msg">{{ msg }}</div>{% endif %}
 <div class="stats">
   {% for s in stats %}<div class="stat"><b>{{ s.c }}</b>{{ s.status }}</div>{% endfor %}
 </div>

 <h2>Replies needing your decision ({{ actionable|length }})</h2>
 {% if not actionable %}<p style="color:#5b6b7a">Nothing waiting. 🎉</p>{% endif %}
 {% for item in actionable %}
 <div class="card">
   <div class="row"><span class="co">{{ item.lead.company }}</span>
     <span class="tag">{{ item.tag }}</span></div>
   <div class="meta">{{ item.lead.area or '' }} · {{ item.lead.contact_email or '' }} · {{ item.lead.phone or '' }}</div>
   {% if item.reply %}<div class="bubble">📩 {{ item.reply }}</div>{% endif %}
   <div class="agent">Book an in-person meeting? Pick a slot:</div>
   <div class="slots">
     {% for slot in slots %}
     <form method="post" action="/book">
       <input type="hidden" name="lead_id" value="{{ item.lead.id }}">
       <input type="hidden" name="when" value="{{ slot.iso }}">
       <button type="submit">{{ slot.label }}</button>
     </form>
     {% endfor %}
   </div>
   <div class="slots">
     <form method="post" action="/book">
       <input type="hidden" name="lead_id" value="{{ item.lead.id }}">
       <input type="datetime-local" name="when" required>
       <button type="submit" class="ghost">Custom time</button>
     </form>
     <form method="post" action="/action">
       <input type="hidden" name="lead_id" value="{{ item.lead.id }}">
       <input type="hidden" name="action" value="not_interested">
       <button type="submit" class="ghost">Not interested</button>
     </form>
     <form method="post" action="/action">
       <input type="hidden" name="lead_id" value="{{ item.lead.id }}">
       <input type="hidden" name="action" value="dismiss">
       <button type="submit" class="ghost">Dismiss</button>
     </form>
   </div>
 </div>
 {% endfor %}

 <h2>Upcoming meetings ({{ booked|length }})</h2>
 {% for b in booked %}
 <div class="card"><span class="co">{{ b.company }}</span>
   <div class="meta">{{ b.contact_email or '' }} · {{ b.phone or '' }}</div>
   <div class="booked">📅 {{ b.meeting_time }}</div></div>
 {% endfor %}
 {% if not booked %}<p style="color:#5b6b7a">No meetings booked yet.</p>{% endif %}
</div></body></html>
""")

LOGIN = Template("""
<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Sign in</title>
<style>body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f3d5e;color:#fff;
display:flex;height:100vh;align-items:center;justify-content:center;margin:0}
form{background:#fff;color:#1a2733;padding:24px;border-radius:12px;min-width:280px}
input{width:100%;padding:10px;margin:8px 0;border:1px solid #ccd;border-radius:8px;box-sizing:border-box}
button{width:100%;padding:10px;background:#0f3d5e;color:#fff;border:0;border-radius:8px;font-size:15px}
.err{color:#b00020;font-size:13px}</style></head><body>
<form method="post" action="/login">
 <b>Deep Cargo Movers — Outreach</b>
 {% if error %}<div class="err">{{ error }}</div>{% endif %}
 <input type="password" name="token" placeholder="Access token" autofocus>
 <button type="submit">Sign in</button>
</form></body></html>
""")


def create_app(deps: AppDeps) -> FastAPI:
    app = FastAPI(title="Courier Outreach Console")
    token = deps.config.app_access_token

    def authed(request: Request) -> bool:
        return bool(token) and request.cookies.get("access") == token

    def redirect(path: str) -> RedirectResponse:
        return RedirectResponse(path, status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    def login_form(error: str = ""):
        return LOGIN.render(error=error)

    @app.post("/login")
    def login(token_value: str = Form(alias="token")):
        if token and token_value == token:
            resp = redirect("/")
            resp.set_cookie("access", token, httponly=True, samesite="lax")
            return resp
        return redirect("/login?error=" + quote("Wrong token"))

    @app.get("/logout")
    def logout():
        resp = redirect("/login")
        resp.delete_cookie("access")
        return resp

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, msg: str = ""):
        if not authed(request):
            return redirect("/login")
        conn = deps.connect()
        try:
            actionable = []
            for lead in conn.execute(
                "SELECT * FROM leads WHERE status IN (?,?) ORDER BY updated_at DESC",
                _ACTIONABLE,
            ).fetchall():
                reply = conn.execute(
                    "SELECT body FROM messages WHERE lead_id=? AND direction='inbound' "
                    "ORDER BY id DESC LIMIT 1", (lead["id"],)).fetchone()
                actionable.append({
                    "lead": lead,
                    "reply": (reply["body"] if reply else "")[:600],
                    "tag": lead["status"].replace("replied_", ""),
                })
            booked = conn.execute(
                "SELECT * FROM leads WHERE status=? ORDER BY meeting_time",
                (LeadStatus.BOOKED.value,)).fetchall()
            stats = conn.execute(
                "SELECT status, COUNT(*) c FROM leads GROUP BY status ORDER BY c DESC"
            ).fetchall()
            slots = [{"iso": s.isoformat(), "label": s.strftime("%a %d %b, %I:%M %p")}
                     for s in propose_slots(deps.config.booking, deps.now())]
            return DASHBOARD.render(actionable=actionable, booked=booked,
                                    stats=stats, slots=slots, msg=msg)
        finally:
            conn.close()

    @app.post("/book")
    def book(request: Request, lead_id: int = Form(...), when: str = Form(...)):
        if not authed(request):
            return redirect("/login")
        conn = deps.connect()
        try:
            start_dt = datetime.fromisoformat(when)
            deps.booker(deps.config, conn, lead_id, start_dt,
                        smtp_config=deps.smtp_config)
            msg = "Meeting booked and confirmation sent."
        except Exception as err:
            log.exception("booking failed")
            msg = f"Booking failed: {err}"
        finally:
            conn.close()
        return redirect("/?msg=" + quote(msg))

    @app.post("/action")
    def action(request: Request, lead_id: int = Form(...), action: str = Form(...)):
        if not authed(request):
            return redirect("/login")
        status = {"not_interested": LeadStatus.REPLIED_NEGATIVE,
                  "dismiss": LeadStatus.CLOSED}.get(action)
        conn = deps.connect()
        try:
            if status:
                db.set_status(conn, lead_id, status)
                msg = f"Lead marked {status.value}."
            else:
                msg = "Unknown action."
        finally:
            conn.close()
        return redirect("/?msg=" + quote(msg))

    return app


def build_default_app() -> FastAPI:
    """Production entry: build deps from environment."""
    config = Config.load()
    smtp = SmtpConfig.load()
    return create_app(AppDeps(config=config, smtp_config=smtp,
                              db_path=config.database_path))
