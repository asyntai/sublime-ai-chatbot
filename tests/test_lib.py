"""Tests for lib/api.py and lib/format.py in plain Python, against a real
local HTTP server that copies the Asyntai /api/v1/ answers.

    python tests/test_lib.py
"""

import json
import os
import sys
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from lib import api  # noqa: E402
from lib import format as fmt  # noqa: E402

GOOD_KEY = "good-key"
FREE_KEY = "free-key"
NOW = datetime.now(timezone.utc)


def iso(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


class FakeAsyntai(BaseHTTPRequestHandler):
    calls = []
    knowledge = []
    next_id = 0

    def log_message(self, *args):
        pass

    def reply(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_any(self, method):
        parts = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length else None
        FakeAsyntai.calls.append({
            "method": method, "path": parts.path, "query": query, "body": body,
            "auth": self.headers.get("Authorization"), "ua": self.headers.get("User-Agent"),
        })
        if parts.path == "/__state":
            FakeAsyntai.calls.pop()
            return self.reply(200, {"calls": FakeAsyntai.calls, "knowledge": FakeAsyntai.knowledge})
        auth = self.headers.get("Authorization")
        if auth == "Bearer " + FREE_KEY:
            return self.reply(403, {"success": False, "error": "API access requires a paid plan (Starter, Standard, or Pro)."})
        if auth != "Bearer " + GOOD_KEY:
            return self.reply(401, {"success": False, "error": "Invalid API key"})

        p = parts.path
        if p == "/api/v1/account/":
            return self.reply(200, {"success": True, "account": {"email": "owner@example.com", "plan": "pro"}})
        if p == "/api/v1/sessions/":
            return self.reply(200, {"success": True, "sessions": [
                {"session_id": "abc123", "first_message": "Do you ship to Canada?", "message_count": 4,
                 "last_message_at": iso(5), "website_domain": "shop.example.com", "country": "CA"},
                {"session_id": "api_sublime_ask_1_x", "first_message": "owner question"},
                {"session_id": "api_vscode_ask_1_x", "first_message": "owner question"},
                {"session_id": "flow_ask_1_x", "first_message": "owner question"},
            ]})
        if p == "/api/v1/leads/":
            return self.reply(200, {"success": True, "leads": [
                {"session_id": "abc123", "email": "jane@example.com", "phone": "+1 555", "started_at": iso(120), "page_url": "https://shop.example.com/p"},
                {"session_id": "", "phone": "+44 20"},
            ]})
        if p == "/api/v1/tickets/":
            return self.reply(200, {"success": True, "tickets": [
                {"session_id": "abc123", "ticket_number": "42", "subject": "Refund", "status": "open", "visitor_email": "jane@example.com", "created_at": iso(60 * 30)},
            ]})
        if p == "/api/v1/conversations/":
            return self.reply(200, {"success": True, "messages": [
                {"role": "user", "content": "Do you ship to Canada?", "timestamp": iso(6)},
                {"role": "assistant", "content": "Yes, we ship to **Canada**.", "timestamp": iso(5)},
                {"role": "assistant", "sender_type": "human", "agent_name": "Tom", "content": "Hi, Tom here.", "timestamp": iso(4)},
            ]})
        if p == "/api/v1/chat/" and method == "POST":
            return self.reply(200, {"success": True, "response": "Echo: " + body["message"], "session_id": "api_" + body["session_id"]})
        if p == "/api/v1/knowledge/" and method == "GET":
            return self.reply(200, {"success": True, "entries": list(FakeAsyntai.knowledge)})
        if p == "/api/v1/knowledge/text/" and method == "POST":
            if len(body.get("content") or "") < 10:
                return self.reply(400, {"success": False, "error": "content must be at least 10 characters"})
            FakeAsyntai.next_id += 1
            entry = {"id": "kb%d" % FakeAsyntai.next_id, "title": body["title"], "type": "text"}
            FakeAsyntai.knowledge.append(entry)
            return self.reply(200, {"success": True, "id": entry["id"], "title": body["title"], "chunks_created": 2})
        if p.startswith("/api/v1/knowledge/") and method == "DELETE":
            entry_id = p.rstrip("/").rsplit("/", 1)[-1]
            FakeAsyntai.knowledge = [e for e in FakeAsyntai.knowledge if e["id"] != entry_id]
            return self.reply(200, {"success": True})
        if p == "/api/v1/limit/":
            return self.reply(429, {"success": False})
        if p == "/api/v1/broken/":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"<html>oops</html>")
            return
        return self.reply(404, {"success": False, "error": "Not found"})

    def do_GET(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")

    def do_DELETE(self):
        self.handle_any("DELETE")


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeAsyntai)
        cls.base = "http://127.0.0.1:%d" % cls.server.server_port
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeAsyntai.calls = []
        FakeAsyntai.knowledge = []
        self.c = api.Client(" " + GOOD_KEY + " ", self.base)

    def test_no_key_never_calls(self):
        c = api.Client("", self.base)
        self.assertFalse(c.has_key)
        with self.assertRaises(api.AsyntaiError) as e:
            c.sessions()
        self.assertIn("Set API Key", e.exception.message)
        self.assertEqual(FakeAsyntai.calls, [])

    def test_key_is_trimmed_and_sent_as_bearer(self):
        self.c.account()
        self.assertEqual(FakeAsyntai.calls[0]["auth"], "Bearer " + GOOD_KEY)
        self.assertEqual(FakeAsyntai.calls[0]["ua"], api.USER_AGENT)

    def test_account(self):
        self.assertEqual(self.c.account()["email"], "owner@example.com")

    def test_wrong_key(self):
        with self.assertRaises(api.AsyntaiError) as e:
            api.Client("bad", self.base).account()
        self.assertEqual(e.exception.status, 401)
        self.assertIn("does not accept", e.exception.message)

    def test_free_plan_uses_server_message(self):
        with self.assertRaises(api.AsyntaiError) as e:
            api.Client(FREE_KEY, self.base).account()
        self.assertEqual(e.exception.status, 403)
        self.assertIn("paid plan", e.exception.message)

    def test_limit_and_broken_server(self):
        with self.assertRaises(api.AsyntaiError) as e:
            self.c._get("/api/v1/limit/")
        self.assertIn("message limit", e.exception.message)
        with self.assertRaises(api.AsyntaiError) as e:
            self.c._get("/api/v1/broken/")
        self.assertIn("500", e.exception.message)

    def test_no_server(self):
        with self.assertRaises(api.AsyntaiError) as e:
            api.Client(GOOD_KEY, "http://127.0.0.1:9").account()
        self.assertIn("did not answer", e.exception.message)

    def test_sessions_hide_owner_questions(self):
        rows = self.c.sessions()
        self.assertEqual([r["session_id"] for r in rows], ["abc123"])
        self.assertEqual(FakeAsyntai.calls[0]["query"], {"limit": "50"})

    def test_leads_tickets_messages(self):
        self.assertEqual(len(self.c.leads()), 2)
        self.assertEqual(self.c.tickets()[0]["ticket_number"], "42")
        self.assertEqual(len(self.c.messages("abc123")), 3)
        self.assertEqual(FakeAsyntai.calls[-1]["query"], {"session_id": "abc123", "limit": "100"})

    def test_ask(self):
        sid = api.new_ask_session()
        self.assertTrue(sid.startswith("sublime_ask_"))
        self.assertNotEqual(sid, api.new_ask_session())
        self.assertEqual(self.c.ask("Hello?", sid), "Echo: Hello?")
        self.assertEqual(FakeAsyntai.calls[0]["body"], {"message": "Hello?", "session_id": sid})
        self.assertTrue(api.is_own_question("api_" + sid))

    def test_knowledge_round_trip(self):
        root = self.c.add_text("guide.md", "A long enough text.")
        self.assertEqual(root["chunks_created"], 2)
        entries = self.c.knowledge()
        self.assertEqual([e["title"] for e in entries], ["guide.md"])
        self.assertEqual(FakeAsyntai.calls[-1]["query"], {"limit": "100"})
        self.c.delete_knowledge(entries[0]["id"])
        self.assertEqual(FakeAsyntai.calls[-1]["method"], "DELETE")
        self.assertEqual(self.c.knowledge(), [])

    def test_knowledge_rejects_short_text(self):
        with self.assertRaises(api.AsyntaiError) as e:
            self.c.add_text("x", "short")
        self.assertIn("at least 10", e.exception.message)

    def test_pick_base(self):
        self.assertEqual(api.pick_base(""), api.LIVE_BASE)
        self.assertEqual(api.pick_base("http://127.0.0.1:8019/"), "http://127.0.0.1:8019")
        self.assertEqual(api.pick_base("http://localhost:8000"), "http://localhost:8000")
        self.assertEqual(api.pick_base("https://evil.example.com"), api.LIVE_BASE)
        self.assertEqual(api.pick_base("http://127.0.0.1.evil.com"), api.LIVE_BASE)
        self.assertEqual(api.pick_base("file:///etc/passwd"), api.LIVE_BASE)

    def test_dashboard_urls(self):
        self.assertEqual(self.c.dashboard_url(), self.base + "/dashboard/")
        self.assertEqual(self.c.dashboard_url("a/b c"), self.base + "/chat/a%2Fb%20c/")


class FormatTests(unittest.TestCase):
    def test_ago(self):
        self.assertEqual(fmt.ago(""), "")
        self.assertEqual(fmt.ago("junk"), "")
        self.assertEqual(fmt.ago(iso(0)), "now")
        self.assertEqual(fmt.ago(iso(5)), "5 min ago")
        self.assertEqual(fmt.ago(iso(125)), "2 h ago")
        self.assertEqual(fmt.ago(iso(60 * 24 * 3)), "3 d ago")
        self.assertTrue(fmt.ago("2020-01-02T03:04:05Z").startswith("2020-01-0"))

    def test_one_line(self):
        self.assertEqual(fmt.one_line("a\n  b"), "a b")
        self.assertEqual(len(fmt.one_line("x" * 200, 50)), 50)

    def test_chat_rows(self):
        rows = fmt.chat_rows([{"session_id": "s1", "first_message": "Hi there", "message_count": 1,
                               "last_message_at": iso(5), "website_domain": "a.com", "country": "CZ"}, {}])
        self.assertEqual(rows[0], ("Hi there", "a.com · CZ", "5 min ago · 1 message", "s1"))
        self.assertEqual(rows[1][0], "Chat without a message")

    def test_lead_rows(self):
        rows = fmt.lead_rows([{"email": "j@x.com", "phone": "+1", "session_id": "s"}, {"phone": "+2"}])
        self.assertEqual(rows[0][:2], ("j@x.com", "+1"))
        self.assertEqual(rows[1][:2], ("+2", ""))

    def test_ticket_rows(self):
        rows = fmt.ticket_rows([{"ticket_number": "7", "subject": "Help", "status": "open"}, {"ticket_number": "T-1"}])
        self.assertEqual(rows[0][0], "#7 Help")
        self.assertEqual(rows[0][1], "Open")
        self.assertEqual(rows[1][0], "T-1 No subject")

    def test_transcript(self):
        text = fmt.transcript("abc", [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
            {"role": "assistant", "sender_type": "human", "agent_name": "Tom", "content": ""},
        ], "https://asyntai.com/chat/abc/")
        self.assertIn("# Chat abc", text)
        self.assertIn("## Visitor\n\nHi", text)
        self.assertIn("## Chatbot\n\nHello", text)
        self.assertIn("## Tom\n\n(empty message)", text)
        self.assertIn("This chat has no messages.", fmt.transcript("x", [], "u"))

    def test_exchange_and_titles(self):
        self.assertEqual(fmt.exchange(" Q ", " A "), "## You\n\nQ\n\n## Your chatbot\n\nA\n\n")
        self.assertIn("empty answer", fmt.exchange("Q", ""))
        self.assertEqual(fmt.knowledge_title("faq.md", False), "faq.md")
        self.assertEqual(fmt.knowledge_title("faq.md", True), "faq.md (selection)")
        self.assertEqual(fmt.knowledge_title("", False), "Untitled")


if __name__ == "__main__":
    unittest.main(verbosity=2)
