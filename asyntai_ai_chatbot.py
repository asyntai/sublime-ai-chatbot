# Copyright (c) Asyntai. Licensed under the MIT license.
"""Asyntai AI Chatbot for Sublime Text.

Ask your website chatbot from the editor, read recent chats, leads and
tickets, and add the file you are writing to your chatbot's knowledge base.
Every network call runs on the async thread; every view change runs on the
main thread.
"""

import webbrowser

import sublime
import sublime_plugin

from .lib import api
from .lib import format as fmt

SETTINGS_FILE = "Asyntai AI Chatbot.sublime-settings"
MARKDOWN = "Packages/Markdown/Markdown.sublime-syntax"
SESSION_SETTING = "asyntai_ask_session"
MIN_KNOWLEDGE_CHARS = 10


def settings():
    return sublime.load_settings(SETTINGS_FILE)


def client():
    s = settings()
    return api.Client(s.get("api_key", ""), api.pick_base(s.get("base_url", "")))


def status(window, text):
    (window or sublime.active_window()).status_message("Asyntai: " + text)


def show_error(error):
    message = error.message if isinstance(error, api.AsyntaiError) else (str(error) or error.__class__.__name__)
    sublime.error_message("Asyntai AI Chatbot\n\n" + message)


def ensure_key(window):
    if client().has_key:
        return True
    if sublime.ok_cancel_dialog(
        "Asyntai AI Chatbot needs your Asyntai API key.\n\n"
        "Find the key in your Asyntai dashboard under Settings, API.",
        "Add API Key",
    ):
        window.run_command("asyntai_set_api_key")
    return False


def run_async(window, busy, work, done):
    """Run `work()` off the main thread, then `done(result)` on it."""
    status(window, busy)

    def worker():
        try:
            result = work()
        except Exception as e:
            # Python clears `e` when the except block ends, so bind it now.
            sublime.set_timeout(lambda error=e: (status(window, "failed"), show_error(error)), 0)
            return
        sublime.set_timeout(lambda: done(result), 0)

    sublime.set_timeout_async(worker, 0)


def new_view(window, name, text, session=None):
    view = window.new_file()
    view.set_name(name)
    view.set_scratch(True)
    view.assign_syntax(MARKDOWN)
    view.settings().set("word_wrap", True)
    if session:
        view.settings().set(SESSION_SETTING, session)
    append(view, text)
    view.set_read_only(True)
    return view


def append(view, text):
    view.run_command("append", {"characters": text, "force": True, "scroll_to_end": True})


# -- API key -----------------------------------------------------------------

class AsyntaiSetApiKeyCommand(sublime_plugin.WindowCommand):
    def run(self):
        self.window.show_input_panel("Asyntai API key:", "", self.check, None, None)

    def check(self, key):
        key = (key or "").strip()
        if not key:
            return
        probe = api.Client(key, client().base)
        run_async(self.window, "checking your API key…", probe.account, lambda account: self.save(key, account))

    def save(self, key, account):
        s = settings()
        s.set("api_key", key)
        sublime.save_settings(SETTINGS_FILE)
        status(self.window, "connected as %s" % (api._s(account, "email") or "your account"))


class AsyntaiSignOutCommand(sublime_plugin.WindowCommand):
    def run(self):
        s = settings()
        s.erase("api_key")
        sublime.save_settings(SETTINGS_FILE)
        status(self.window, "API key removed")

    def is_enabled(self):
        return client().has_key


# -- ask your chatbot -------------------------------------------------------

def answer_view(window):
    view = window.active_view()
    if view and view.settings().get(SESSION_SETTING):
        return view
    return None


class AsyntaiAskCommand(sublime_plugin.WindowCommand):
    """Ask a question. In an answer tab, the question continues that chat."""

    def run(self, question=None, new_conversation=False, from_selection=False):
        if not ensure_key(self.window):
            return
        target = None if new_conversation else answer_view(self.window)
        if question:
            self.ask(question, target)
            return
        initial = selected_text(self.window.active_view()) if from_selection else ""
        prompt = "Ask a follow-up question:" if target else "Ask your chatbot:"
        self.window.show_input_panel(prompt, fmt.one_line(initial, 2000), lambda q: self.ask(q, target), None, None)

    def ask(self, question, target):
        question = (question or "").strip()
        if not question:
            return
        session = target.settings().get(SESSION_SETTING) if target else api.new_ask_session()
        c = client()

        def done(answer):
            text = fmt.exchange(question, answer)
            if target and target.is_valid():
                append(target, text)
                self.window.focus_view(target)
            else:
                new_view(self.window, "Asyntai: " + fmt.one_line(question, 40), fmt.answer_header() + text, session)
            status(self.window, "answer received")

        run_async(self.window, "your chatbot is answering…", lambda: c.ask(question, session), done)


def selected_text(view):
    if not view:
        return ""
    return "\n".join(view.substr(r) for r in view.sel() if not r.empty()).strip()


# -- chats, leads, tickets --------------------------------------------------

class _ListCommand(sublime_plugin.WindowCommand):
    noun = ""
    empty = ""

    def fetch(self, c):
        raise NotImplementedError

    def rows(self, items):
        raise NotImplementedError

    def run(self):
        if not ensure_key(self.window):
            return
        c = client()
        run_async(self.window, "loading %s…" % self.noun, lambda: self.rows(self.fetch(c)), lambda rows: self.show(c, rows))

    def show(self, c, rows):
        status(self.window, "%d %s" % (len(rows), self.noun))
        if not rows:
            sublime.message_dialog(self.empty)
            return
        items = [sublime.QuickPanelItem(title, details, annotation) for title, details, annotation, _ in rows]

        def picked(index):
            if index < 0:
                return
            session_id = rows[index][3]
            if not session_id:
                sublime.message_dialog("This item has no chat to show.")
                return
            open_transcript(self.window, c, session_id)

        self.window.show_quick_panel(items, picked, placeholder="Pick one to read the chat")


def open_transcript(window, c, session_id):
    def done(messages):
        new_view(window, "Asyntai chat " + session_id[-12:], fmt.transcript(session_id, messages, c.dashboard_url(session_id)))
        status(window, "chat loaded")

    run_async(window, "loading the chat…", lambda: c.messages(session_id), done)


class AsyntaiRecentChatsCommand(_ListCommand):
    noun = "chats"
    empty = "No chats yet. A chat appears here as soon as a visitor writes to your chatbot."

    def fetch(self, c):
        return c.sessions()

    def rows(self, items):
        return fmt.chat_rows(items)


class AsyntaiLeadsCommand(_ListCommand):
    noun = "leads"
    empty = "No leads yet. A lead appears when a visitor leaves an email address or a phone number."

    def fetch(self, c):
        return c.leads()

    def rows(self, items):
        return fmt.lead_rows(items)


class AsyntaiTicketsCommand(_ListCommand):
    noun = "tickets"
    empty = "No tickets yet. A ticket appears when your chatbot hands a chat over to your team."

    def fetch(self, c):
        return c.tickets()

    def rows(self, items):
        return fmt.ticket_rows(items)


# -- knowledge base ---------------------------------------------------------

class AsyntaiAddToKnowledgeBaseCommand(sublime_plugin.TextCommand):
    """Send this file, or the selected text, to the chatbot's knowledge base."""

    def run(self, edit):
        window = self.view.window() or sublime.active_window()
        if not ensure_key(window):
            return
        selection = selected_text(self.view)
        content = selection or self.view.substr(sublime.Region(0, self.view.size())).strip()
        if len(content) < MIN_KNOWLEDGE_CHARS:
            sublime.message_dialog("There is not enough text to add. Write at least %d characters." % MIN_KNOWLEDGE_CHARS)
            return
        title = fmt.knowledge_title(self.file_name(), bool(selection))
        what = "the selected text" if selection else "this file"
        if not sublime.ok_cancel_dialog(
            "Add %s to your chatbot's knowledge base as \"%s\"?\n\n"
            "Your chatbot can then use it in answers to visitors." % (what, title),
            "Add",
        ):
            return
        c = client()
        run_async(window, "checking your knowledge base…", c.knowledge, lambda entries: self.send(window, c, title, content, entries))

    def send(self, window, c, title, content, entries):
        old = [api._s(e, "id") for e in entries if api._s(e, "title") == title and api._s(e, "id")]
        if old:
            choice = sublime.yes_no_cancel_dialog(
                "Your knowledge base already has \"%s\".\n\nReplace it with the new text?" % title,
                "Replace", "Add as a new item",
            )
            if choice == sublime.DIALOG_CANCEL:
                return
            if choice != sublime.DIALOG_YES:
                old = []

        def work():
            for entry_id in old:
                c.delete_knowledge(entry_id)
            return c.add_text(title, content)

        def done(root):
            chunks = api._s(root, "chunks_created")
            status(window, "added \"%s\" to your knowledge base%s" % (title, " (%s parts)" % chunks if chunks else ""))

        run_async(window, "adding to your knowledge base…", work, done)

    def file_name(self):
        path = self.view.file_name()
        if path:
            return path.replace("\\", "/").rsplit("/", 1)[-1]
        return self.view.name() or ""

    def is_enabled(self):
        return self.view.size() > 0


# -- dashboard --------------------------------------------------------------

class AsyntaiOpenDashboardCommand(sublime_plugin.WindowCommand):
    def run(self):
        webbrowser.open(client().dashboard_url())
