# Copyright (c) Asyntai. Licensed under the MIT license.
"""Every call to Asyntai goes through this module.

The package talks to the public API (/api/v1/) with the account owner's API
key. The key only leaves the machine in the Authorization header of a call to
asyntai.com. Only the Python standard library is used, and nothing here
imports `sublime`, so the tests run in plain Python.
"""

import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

LIVE_BASE = "https://asyntai.com"
USER_AGENT = "AsyntaiSublimeText/1.0"
PAGE_SIZE = 50
TIMEOUT = 60
LOCAL_HOSTS = ("127.0.0.1", "localhost")

# Questions asked from the editor go through the same API as a visitor chat,
# so Asyntai stores them as sessions. They are the owner's own questions, so
# Recent Chats leaves them out. The other Asyntai apps mark theirs the same way.
ASK_MARKER = "sublime_ask_"
OWN_MARKERS = (ASK_MARKER, "vscode_ask_", "flow_ask_", "cmdpal_ask_", "raycast_ask_", "ext_ask_")


class AsyntaiError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.message = message
        self.status = status


def new_ask_session():
    return "%s%d_%s" % (ASK_MARKER, int(time.time() * 1000), secrets.token_hex(3))


def is_own_question(session_id):
    if not session_id:
        return False
    # The chat API stores a caller's session id as "api_" + the id.
    sid = session_id[4:] if session_id.startswith("api_") else session_id
    return sid.startswith(OWN_MARKERS)


def pick_base(value):
    """Only asyntai.com, or a server on this machine for tests."""
    value = (value or "").strip().rstrip("/")
    if not value:
        return LIVE_BASE
    parts = urllib.parse.urlsplit(value)
    if parts.scheme in ("http", "https") and parts.hostname in LOCAL_HOSTS:
        return value
    return LIVE_BASE


class Client:
    def __init__(self, api_key, base=LIVE_BASE):
        self.api_key = (api_key or "").strip()
        self.base = (base or LIVE_BASE).rstrip("/")

    @property
    def has_key(self):
        return bool(self.api_key)

    def dashboard_url(self, session_id=None):
        if not session_id:
            return self.base + "/dashboard/"
        return "%s/chat/%s/" % (self.base, urllib.parse.quote(session_id, safe=""))

    # -- reads ---------------------------------------------------------

    def account(self):
        root = self._get("/api/v1/account/")
        account = root.get("account")
        return account if isinstance(account, dict) else {}

    def sessions(self):
        root = self._get("/api/v1/sessions/", limit=PAGE_SIZE)
        return [r for r in _rows(root, "sessions") if not is_own_question(_s(r, "session_id"))]

    def leads(self):
        return _rows(self._get("/api/v1/leads/", limit=PAGE_SIZE), "leads")

    def tickets(self):
        return _rows(self._get("/api/v1/tickets/", limit=PAGE_SIZE), "tickets")

    def messages(self, session_id):
        root = self._get("/api/v1/conversations/", session_id=session_id, limit=100)
        return _rows(root, "messages")

    def knowledge(self):
        return _rows(self._get("/api/v1/knowledge/", limit=100), "entries")

    # -- writes --------------------------------------------------------

    def ask(self, question, session_id):
        root = self._send("POST", "/api/v1/chat/", {"message": question, "session_id": session_id})
        return _s(root, "response") or ""

    def add_text(self, title, content):
        return self._send("POST", "/api/v1/knowledge/text/", {"title": title, "content": content})

    def delete_knowledge(self, entry_id):
        return self._send("DELETE", "/api/v1/knowledge/%s/" % urllib.parse.quote(entry_id, safe=""), None)

    # -- plumbing ------------------------------------------------------

    def _get(self, path, **params):
        query = {k: str(v) for k, v in params.items() if v not in (None, "")}
        if query:
            path = path + "?" + urllib.parse.urlencode(query)
        return self._send("GET", path, None)

    def _send(self, method, path, body):
        if not self.has_key:
            raise AsyntaiError("Add your Asyntai API key first: run \"Asyntai: Set API Key\".")

        data = None
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        status = 0
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                status = response.status
                text = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            status = e.code
            text = e.read().decode("utf-8", "replace") if e.fp else ""
        except Exception:
            raise AsyntaiError("Asyntai did not answer. Check your connection.")

        try:
            root = json.loads(text) if text.strip() else {}
        except ValueError:
            root = None

        error = _s(root, "error") if isinstance(root, dict) else None
        if status == 401:
            raise AsyntaiError("Asyntai does not accept this API key. Run \"Asyntai: Set API Key\" and paste a new key.", status)
        if status == 403:
            raise AsyntaiError(error or "The Asyntai API needs the Starter plan or higher.", status)
        if status == 429:
            raise AsyntaiError(error or "Your chatbot reached its message limit.", status)
        failed = isinstance(root, dict) and root.get("success") is False
        if status >= 400 or failed or not isinstance(root, dict):
            raise AsyntaiError(error or "Asyntai answered with status %d." % status, status)
        return root


def _rows(root, name):
    rows = root.get(name) if isinstance(root, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _s(row, name):
    if not isinstance(row, dict):
        return None
    value = row.get(name)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return value if isinstance(value, str) else None
