# End-to-end driver that runs INSIDE a real Sublime Text.
#
# tests/run_e2e.py copies the package into a portable Sublime Text, copies
# this file next to it as zz_e2e.py (so it shares the package's plugin host
# and its stubs reach the package), writes e2e_config.json and starts the
# editor. The driver runs every command the user can run, writes the results
# to the config's "out" file and closes the editor.
#
# Dialogs, input panels and quick panels are stubbed: a modal dialog would
# block the editor, and nobody sits at the hidden desktop the test uses.

import json
import re
import os
import sys
import time
import traceback
import urllib.request

import sublime
import sublime_plugin  # noqa: F401  (keeps the file a normal plugin)

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(open(os.path.join(HERE, "e2e_config.json"), encoding="utf-8"))
PKG = sys.modules[__name__.rsplit(".", 1)[0] + ".asyntai_ai_chatbot"]

results = []
record = {"dialogs": [], "errors": [], "messages": [], "status": [], "panels": [], "inputs": []}
inputs = []           # values the next input panels return; None = keep the initial text
answers = {"ok": True, "ync": sublime.DIALOG_YES, "pick": 0}


def check(name, ok, detail=""):
    results.append({"name": name, "ok": bool(ok), "detail": str(detail)[-900:]})


# -- stubs ------------------------------------------------------------------

def ok_cancel(msg, ok_title="", title=""):
    record["dialogs"].append(msg)
    return answers["ok"]


def yes_no_cancel(msg, yes_title="", no_title="", title=""):
    record["dialogs"].append(msg)
    return answers["ync"]


sublime.ok_cancel_dialog = ok_cancel
sublime.yes_no_cancel_dialog = yes_no_cancel
sublime.error_message = lambda msg: record["errors"].append(msg)
sublime.message_dialog = lambda msg: record["messages"].append(msg)
_status = sublime.Window.status_message
sublime.Window.status_message = lambda self, msg: (record["status"].append(msg), _status(self, msg))


def input_panel(self, caption, initial, on_done, on_change, on_cancel):
    record["inputs"].append((caption, initial))
    value = inputs.pop(0) if inputs else None
    sublime.set_timeout(lambda: on_done(initial if value is None else value), 10)


def quick_panel(self, items, on_select, flags=0, selected_index=-1, on_highlight=None, placeholder=""):
    record["panels"].append([(i.trigger, i.details, i.annotation) for i in items])
    sublime.set_timeout(lambda: on_select(answers["pick"]), 10)


sublime.Window.show_input_panel = input_panel
sublime.Window.show_quick_panel = quick_panel


# -- helpers ----------------------------------------------------------------

FAKE = CONFIG.get("mode") == "fake"


def server_state():
    with urllib.request.urlopen(CONFIG["base_url"] + "/__state", timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def rig_client():
    return PKG.api.Client(CONFIG["good_key"], CONFIG["base_url"])


def kb():
    """Text items in the knowledge base."""
    if FAKE:
        return server_state()["knowledge"]
    return [e for e in rig_client().knowledge() if e.get("type") == "text"]


def kb_ids():
    return sorted(e["id"] for e in kb())


def user_questions(session_id):
    """What the editor asked in one chat, read back from the server."""
    if FAKE:
        return [c["body"]["message"] for c in server_state()["calls"]
                if c["path"] == "/api/v1/chat/" and c["body"]["session_id"] == session_id]
    return [m.get("content") for m in rig_client().messages("api_" + session_id) if m.get("role") == "user"]


def last_posted(path):
    return [c for c in server_state()["calls"] if c["path"] == path][-1]["body"]


def views(window):
    # Sorted by id, oldest first: Sublime opens a new tab next to the active
    # tab, so the tab order does not tell which view is the newest.
    return sorted((v for v in window.views() if v.name().startswith("Asyntai")), key=lambda v: v.id())


def text(view):
    return view.substr(sublime.Region(0, view.size()))


def set_key(value):
    s = sublime.load_settings("Asyntai.sublime-settings")
    if value is None:
        s.erase("api_key")
    else:
        s.set("api_key", value)
    s.set("base_url", CONFIG["base_url"])
    sublime.save_settings("Asyntai.sublime-settings")


def key():
    return sublime.load_settings("Asyntai.sublime-settings").get("api_key", "")


def buffer(window, name, body, select_all=False):
    view = window.new_file()
    view.set_name(name)
    view.run_command("append", {"characters": body})
    view.sel().clear()
    view.sel().add(sublime.Region(0, view.size()) if select_all else sublime.Region(0, 0))
    window.focus_view(view)
    return view


# -- the scenario, as a generator: each `yield` is (condition, timeout) ------

def scenario(w):
    live = CONFIG.get("mode") == "live"
    check("python host", True, sys.version.split()[0])
    check("commands loaded", hasattr(PKG, "AsyntaiAskCommand"))

    # 1. No key: the command asks for the key and never calls the server.
    set_key(None)
    answers["ok"] = False
    n = len(record["dialogs"])
    w.run_command("asyntai_recent_chats")
    yield (lambda: len(record["dialogs"]) > n, 5)
    check("no key: asks for the key", "needs your Asyntai API key" in record["dialogs"][-1], record["dialogs"][-1])
    check("no key: no list opened", not record["panels"])
    answers["ok"] = True

    # 2. A wrong key is refused and not saved.
    inputs[:] = ["wrong-key"]
    n = len(record["errors"])
    w.run_command("asyntai_set_api_key")
    yield (lambda: len(record["errors"]) > n, 30)
    check("wrong key refused", "does not accept this API key" in record["errors"][-1], record["errors"][-1])
    check("wrong key not saved", key() == "", key()[:4])

    # 3. The good key is checked and saved.
    inputs[:] = ["  " + CONFIG["good_key"] + "  "]
    w.run_command("asyntai_set_api_key")
    yield (lambda: key() == CONFIG["good_key"], 30)
    check("good key saved (trimmed)", key() == CONFIG["good_key"])
    check("connected status", any(m.startswith("Asyntai: connected as ") for m in record["status"]),
          [m for m in record["status"] if "connected" in m][-1:] )

    # 4. Recent chats, then the transcript of the first one.
    before = len(views(w))
    w.run_command("asyntai_recent_chats")
    yield (lambda: len(views(w)) > before or record["messages"], 60)
    chats = record["panels"][-1] if record["panels"] else []
    owner = [c for c in chats if c[0] == "owner question"]
    check("chats listed", len(chats) >= 1 if live else len(chats) == 1, "%d rows, first %r" % (len(chats), chats[:1]))
    check("own questions hidden", not owner, owner)
    if not live:
        check("chat row", chats and chats[0][0] == "Do you ship to Canada?", chats[:1])
    if chats:
        t = text(views(w)[-1])
        check("chat transcript opens", t.startswith("# Chat ") and "## " in t, t[:200])
        check("transcript is Markdown + read-only", views(w)[-1].is_read_only()
              and "Markdown" in (views(w)[-1].settings().get("syntax") or ""), views(w)[-1].settings().get("syntax"))
        if FAKE:
            check("transcript speakers", "## Visitor" in t and "## Chatbot" in t and "## Tom" in t, t[:300])
        elif not live:
            check("transcript speakers", re.search(r"## Visitor \([^)]+\)\n\nDo you ship to Canada\?", t)
                  and re.search(r"## Chatbot \([^)]+\)\n\nRig answer to: Do you ship to Canada\?", t), t[:300])

    # 5. Leads.
    n = len(record["panels"])
    before = len(views(w))
    w.run_command("asyntai_leads")
    yield (lambda: len(record["panels"]) > n or len(record["messages"]) > 0, 60)
    leads = record["panels"][-1] if len(record["panels"]) > n else []
    check("leads listed", leads or live, leads[:2])
    if leads and FAKE:
        check("lead row", leads[0][0] == "jane@example.com" and leads[1][0] == "+44 20", leads)
    elif leads and not live:
        check("lead row", leads[0][0] == "jane@example.com", leads)
    if leads:
        yield (lambda: len(views(w)) > before or any("no chat" in m for m in record["messages"]), 60)
        check("lead opens its chat", len(views(w)) > before or any("no chat" in m for m in record["messages"]))

    # 6. Tickets.
    n = len(record["panels"])
    m = len(record["messages"])
    before = len(views(w))
    w.run_command("asyntai_tickets")
    yield (lambda: len(record["panels"]) > n or len(record["messages"]) > m, 60)
    tickets = record["panels"][-1] if len(record["panels"]) > n else []
    if live:
        check("tickets listed or empty notice", tickets or "No tickets yet" in " ".join(record["messages"]), tickets[:1])
    else:
        want = "#42 Refund" if FAKE else "TKT-00001 Refund for order 1001"
        check("tickets listed", tickets and tickets[0][0] == want and tickets[0][1].startswith("Open"), tickets)
    if tickets:
        # Wait for the picked ticket's chat, so it is not taken for the answer tab below.
        yield (lambda: len(views(w)) > before, 60)
        check("ticket opens its chat", text(views(w)[-1]).startswith("# Chat "))

    if live and not CONFIG.get("allow_paid"):
        return

    # 7. Ask a question: a new answer tab.
    before = len(views(w))
    q1 = CONFIG.get("question", "Hello from Sublime?")
    w.run_command("asyntai_ask", {"question": q1})
    yield (lambda: len(views(w)) > before, 120)
    ans = views(w)[-1]
    sid = ans.settings().get("asyntai_ask_session") or ""
    t = text(ans)
    check("answer tab opens", t.startswith("# Ask My Chatbot") and "## You\n\n" + q1 in t and "## Your chatbot" in t, t[:400])
    check("ask session marked", sid.startswith("sublime_ask_"), sid)
    if FAKE:
        check("answer text", "Echo: " + q1 in t, t[-120:])
    elif not live:
        check("answer text", "Rig answer to: " + q1 in t, t[-120:])
    if live:
        body = t.split("## Your chatbot", 1)[-1].strip()
        check("live answer has text", len(body) > 20, "%d chars: %s" % (len(body), body[:160]))
        return

    # 8. A follow-up in the answer tab continues the same chat.
    w.focus_view(ans)
    before = len(views(w))
    size = ans.size()
    w.run_command("asyntai_ask", {"question": "And a follow-up?"})
    yield (lambda: ans.size() > size, 60)
    check("follow-up appends to the same tab", len(views(w)) == before and "## You\n\nAnd a follow-up?" in text(ans))
    got = user_questions(sid)
    check("follow-up keeps the session", got == [q1, "And a follow-up?"], got)

    # 9. New conversation: a new tab and a new session.
    w.run_command("asyntai_ask", {"question": "Fresh start?", "new_conversation": True})
    yield (lambda: len(views(w)) > before, 60)
    sid2 = views(w)[-1].settings().get("asyntai_ask_session")
    check("new conversation = new session", sid2 and sid2 != sid and user_questions(sid2) == ["Fresh start?"], sid2)

    # 10. Ask about selection: the input panel starts with the selected text.
    buffer(w, "notes.txt", "What are your opening hours?", select_all=True)
    before = len(views(w))
    inputs[:] = [None]
    w.run_command("asyntai_ask", {"from_selection": True, "new_conversation": True})
    yield (lambda: len(views(w)) > before, 60)
    check("selection prefilled", record["inputs"][-1] == ("Ask your chatbot:", "What are your opening hours?"), record["inputs"][-1])
    sid3 = views(w)[-1].settings().get("asyntai_ask_session")
    got = user_questions(sid3)
    check("selection asked", got == ["What are your opening hours?"], got)

    # 11. Add a file to the knowledge base, replace it, then add a copy.
    if not FAKE:
        # The rig database keeps the items of the last run.
        for e in kb():
            if e["title"] in ("guide.md", "faq.md (selection)"):
                rig_client().delete_knowledge(e["id"])
    start = kb_ids()
    body = "# Returns\n\nYou can return any item within 30 days."
    doc = buffer(w, "guide.md", body)
    answers["ok"] = True
    doc.run_command("asyntai_add_to_knowledge_base")
    yield (lambda: len(kb()) == len(start) + 1, 60)
    items = [e for e in kb() if e["title"] == "guide.md"]
    check("file added to knowledge base", len(items) == 1, kb())
    check("add asked first", "Add this file to your chatbot's knowledge base as \"guide.md\"?" in record["dialogs"][-1], record["dialogs"][-1])
    if FAKE:
        posted = last_posted("/api/v1/knowledge/text/")
        check("whole file sent", posted == {"title": "guide.md", "content": body}, posted)

    first_id = items[0]["id"] if items else ""
    answers["ync"] = sublime.DIALOG_YES
    doc.run_command("asyntai_add_to_knowledge_base")
    yield (lambda: [e["id"] for e in kb() if e["title"] == "guide.md"] not in ([first_id], []), 60)
    items = [e for e in kb() if e["title"] == "guide.md"]
    check("replace keeps one item", len(items) == 1 and items[0]["id"] != first_id, items)
    check("replace asked", "already has \"guide.md\"" in record["dialogs"][-1], record["dialogs"][-1])

    answers["ync"] = sublime.DIALOG_NO
    doc.run_command("asyntai_add_to_knowledge_base")
    yield (lambda: len([e for e in kb() if e["title"] == "guide.md"]) == 2, 60)
    check("'add as new' keeps both", len([e for e in kb() if e["title"] == "guide.md"]) == 2)

    answers["ync"] = sublime.DIALOG_CANCEL
    ids = kb_ids()
    n = len(server_state()["calls"]) if FAKE else 0
    doc.run_command("asyntai_add_to_knowledge_base")
    yield (lambda: False, 3)
    if FAKE:
        later = server_state()["calls"][n:]
        check("cancel sends nothing", [c["method"] for c in later] == ["GET"], later)
    check("cancel changes nothing", kb_ids() == ids)

    answers["ok"] = False
    doc.run_command("asyntai_add_to_knowledge_base")
    yield (lambda: False, 2)
    check("'Cancel' on the first dialog changes nothing", kb_ids() == ids)
    answers["ok"] = True

    sel = buffer(w, "faq.md", "Q: Do you ship abroad?\nA: Yes, to 40 countries.", select_all=True)
    sel.sel().clear()
    sel.sel().add(sublime.Region(23, sel.size()))
    sel.run_command("asyntai_add_to_knowledge_base")
    yield (lambda: any(e["title"] == "faq.md (selection)" for e in kb()), 60)
    check("selection added", any(e["title"] == "faq.md (selection)" for e in kb()))
    if FAKE:
        posted = last_posted("/api/v1/knowledge/text/")
        check("only the selection sent", posted == {"title": "faq.md (selection)", "content": "A: Yes, to 40 countries."}, posted)

    m = len(record["messages"])
    buffer(w, "tiny.txt", "short").run_command("asyntai_add_to_knowledge_base")
    yield (lambda: len(record["messages"]) > m, 5)
    check("short text refused", "not enough text" in record["messages"][-1], record["messages"][-1])

    # 12. The editor's own questions never show in Recent Chats.
    n = len(record["panels"])
    before = len(views(w))
    w.run_command("asyntai_recent_chats")
    yield (lambda: len(views(w)) > before, 60)
    again = record["panels"][-1] if len(record["panels"]) > n else []
    check("own questions still hidden after asking", [r[0] for r in again] == [r[0] for r in chats], again)

    # 13. Sign out.
    w.run_command("asyntai_sign_out")
    yield (lambda: key() == "", 5)
    check("sign out removes the key", key() == "")
    check("no unexpected errors", len(record["errors"]) == 1, record["errors"])


# -- runner -------------------------------------------------------------------

def finish():
    with open(CONFIG["out"], "w", encoding="utf-8") as f:
        json.dump({"results": results, "status": record["status"][-30:]}, f, indent=1)
    sublime.set_timeout(lambda: sublime.run_command("exit"), 300)


def step(gen, cond=None, deadline=0):
    try:
        if cond is not None and not cond() and time.time() < deadline:
            sublime.set_timeout(lambda: step(gen, cond, deadline), 100)
            return
        cond, timeout = next(gen)
        step(gen, cond, time.time() + timeout)
    except StopIteration:
        finish()
    except Exception:
        check("driver crashed", False, traceback.format_exc())
        finish()


def plugin_loaded():
    def start():
        w = sublime.active_window()
        step(scenario(w))
    sublime.set_timeout(start, 1500)
