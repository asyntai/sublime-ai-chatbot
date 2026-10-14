# Copyright (c) Asyntai. Licensed under the MIT license.
"""Labels and Markdown text for the editor. No `sublime` import, so the tests
run in plain Python."""

import re
from datetime import datetime, timezone

from .api import _s


def one_line(text, limit=110):
    line = re.sub(r"\s+", " ", text or "").strip()
    return line if len(line) <= limit else line[: limit - 1] + "…"


def ago(iso, now=None):
    if not iso:
        return ""
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    seconds = max(0, (now - when).total_seconds())
    if seconds < 60:
        return "now"
    if seconds < 3600:
        return "%d min ago" % (seconds // 60)
    if seconds < 86400:
        return "%d h ago" % (seconds // 3600)
    if seconds < 30 * 86400:
        return "%d d ago" % (seconds // 86400)
    return when.astimezone().strftime("%Y-%m-%d")


def joined(*parts):
    return " · ".join(p for p in parts if p)


def messages_label(count):
    if not count or count == "0":
        return ""
    return "1 message" if count == "1" else count + " messages"


# -- quick panel rows: (title, details, annotation, session_id) -------------

def chat_rows(sessions):
    rows = []
    for s in sessions:
        rows.append((
            one_line(_s(s, "first_message")) or "Chat without a message",
            joined(_s(s, "website_domain"), _s(s, "country"), _s(s, "page_url")),
            joined(ago(_s(s, "last_message_at")), messages_label(_s(s, "message_count"))),
            _s(s, "session_id") or "",
        ))
    return rows


def lead_rows(leads):
    rows = []
    for lead in leads:
        email = _s(lead, "email")
        phone = _s(lead, "phone")
        rows.append((
            email or phone or "Lead",
            joined(phone if email else "", _s(lead, "page_url")),
            ago(_s(lead, "started_at")),
            _s(lead, "session_id") or "",
        ))
    return rows


def ticket_rows(tickets):
    rows = []
    for t in tickets:
        number = _s(t, "ticket_number") or ""
        prefix = ("#" if number.isdigit() else "") + number + " " if number else ""
        rows.append((
            one_line(prefix + (_s(t, "subject") or "No subject")),
            joined((_s(t, "status") or "").capitalize(), _s(t, "visitor_email")),
            ago(_s(t, "created_at")),
            _s(t, "session_id") or "",
        ))
    return rows


# -- Markdown views ---------------------------------------------------------

def speaker(message):
    if _s(message, "role") == "user":
        return "Visitor"
    if _s(message, "sender_type") == "human":
        return _s(message, "agent_name") or "Your team"
    return "Chatbot"


def transcript(session_id, messages, dashboard_url):
    out = ["# Chat %s" % session_id, "", "Open in Asyntai: %s" % dashboard_url, ""]
    if not messages:
        out += ["This chat has no messages.", ""]
    for m in messages:
        when = ago(_s(m, "timestamp"))
        out.append("## %s%s" % (speaker(m), " (" + when + ")" if when else ""))
        out.append("")
        out.append((_s(m, "content") or "").strip() or "(empty message)")
        out.append("")
    return "\n".join(out)


def answer_header():
    return (
        "# Ask My Chatbot\n\n"
        "Your chatbot answers from your website, like it answers visitors.\n"
        "Run \"Asyntai: Ask My Chatbot\" in this tab to ask a follow-up question.\n\n"
    )


def exchange(question, answer):
    answer = (answer or "").strip() or "(your chatbot sent an empty answer)"
    return "## You\n\n%s\n\n## Your chatbot\n\n%s\n\n" % (question.strip(), answer)


def knowledge_title(file_name, selection):
    name = file_name or "Untitled"
    return name + " (selection)" if selection else name
