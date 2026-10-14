"""Run tests/sublime_e2e.py inside a real, portable Sublime Text (Windows).

    python tests/run_e2e.py --sublime <portable Sublime Text folder> [--mode fake|live] [--allow-paid]

fake: the editor talks to the fake Asyntai server from tests/test_lib.py on
      127.0.0.1. Every command runs, nothing leaves the machine.
rig:  the editor talks to a local copy of the real Asyntai server
      (--base-url, key in --key-file). Every command runs.
live: the editor talks to https://asyntai.com with TEST_ASYNTAI_API_KEY from
      the repo .env. Read-only commands only, unless --allow-paid (one real
      chatbot answer).

The editor starts on its own hidden Windows desktop, so it never takes the
screen or the keyboard. The key is written only to the portable editor's
folder and is removed after the run.
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.dirname(HERE)
REPO = os.path.abspath(os.path.join(PKG_DIR, "..", "..", ".."))
PACKAGE_NAME = "Asyntai AI Chatbot"
SHIP = [".python-version", "asyntai_ai_chatbot.py", "lib", "Default.sublime-commands", 
        "Main.sublime-menu", "Asyntai.sublime-settings", "messages.json", "messages", "LICENSE"]

sys.path.insert(0, HERE)


def env_key():
    for line in open(os.path.join(REPO, ".env"), encoding="utf-8"):
        if line.startswith("TEST_ASYNTAI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("TEST_ASYNTAI_API_KEY is not in .env")


class STARTUPINFO(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
                ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE),
                ("hStdError", wt.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE), ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


def start_hidden(exe, desktop_name="AsyntaiSublimeTest"):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.CreateDesktopW.restype = wt.HANDLE
    desk = user32.CreateDesktopW(desktop_name, None, None, 0, 0x10000000, None)  # GENERIC_ALL
    if not desk:
        raise OSError("CreateDesktopW failed: %d" % ctypes.get_last_error())
    si = STARTUPINFO()
    si.cb = ctypes.sizeof(si)
    si.lpDesktop = desktop_name
    pi = PROCESS_INFORMATION()
    cmd = ctypes.create_unicode_buffer('"%s"' % exe)
    if not kernel32.CreateProcessW(None, cmd, None, None, False, 0, None, os.path.dirname(exe), ctypes.byref(si), ctypes.byref(pi)):
        raise OSError("CreateProcessW failed: %d" % ctypes.get_last_error())
    return pi.dwProcessId


def install(st, config):
    data = os.path.join(st, "Data")
    target = os.path.join(data, "Packages", PACKAGE_NAME)
    user = os.path.join(data, "Packages", "User")
    shutil.rmtree(target, ignore_errors=True)
    os.makedirs(user, exist_ok=True)
    for name in SHIP:
        src = os.path.join(PKG_DIR, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(target, name), ignore=shutil.ignore_patterns("__pycache__"))
        else:
            os.makedirs(target, exist_ok=True)
            shutil.copy2(src, os.path.join(target, name))
    shutil.copy2(os.path.join(HERE, "sublime_e2e.py"), os.path.join(target, "zz_e2e.py"))
    json.dump(config, open(os.path.join(target, "e2e_config.json"), "w", encoding="utf-8"))
    json.dump({"update_check": False, "hot_exit": "disabled", "remember_open_files": False},
              open(os.path.join(user, "Preferences.sublime-settings"), "w", encoding="utf-8"))
    for stale in ("Asyntai.sublime-settings",):
        path = os.path.join(user, stale)
        if os.path.exists(path):
            os.remove(path)
    # A clean session, so no old window comes back.
    shutil.rmtree(os.path.join(data, "Local"), ignore_errors=True)
    return target, user


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sublime", required=True)
    ap.add_argument("--mode", choices=("fake", "rig", "live"), default="fake")
    ap.add_argument("--base-url", default="http://127.0.0.1:8024")
    ap.add_argument("--key-file", default="")
    ap.add_argument("--allow-paid", action="store_true")
    ap.add_argument("--question", default="")
    ap.add_argument("--timeout", type=int, default=420)
    args = ap.parse_args()

    st = os.path.abspath(args.sublime)
    out = os.path.join(st, "e2e_result.json")
    if os.path.exists(out):
        os.remove(out)

    server = None
    if args.mode == "fake":
        import test_lib
        server = HTTPServer(("127.0.0.1", 0), test_lib.FakeAsyntai)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        config = {"mode": "fake", "base_url": "http://127.0.0.1:%d" % server.server_port, "good_key": test_lib.GOOD_KEY, "out": out}
    elif args.mode == "rig":
        key = open(args.key_file, encoding="utf-8").read().strip()
        config = {"mode": "rig", "base_url": args.base_url, "good_key": key, "out": out}
    else:
        config = {"mode": "live", "base_url": "", "good_key": env_key(), "out": out, "allow_paid": args.allow_paid}
        if args.question:
            config["question"] = args.question

    target, user = install(st, config)
    pid = start_hidden(os.path.join(st, "sublime_text.exe"))
    deadline = time.time() + args.timeout
    try:
        while time.time() < deadline and not os.path.exists(out):
            time.sleep(0.5)
        time.sleep(1)
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        # Never leave the real key on disk.
        for path in (os.path.join(target, "e2e_config.json"), os.path.join(user, "Asyntai.sublime-settings")):
            if os.path.exists(path):
                os.remove(path)
        if server:
            server.shutdown()

    if not os.path.exists(out):
        print("NO RESULT: the driver did not finish in %d s" % args.timeout)
        sys.exit(2)
    report = json.load(open(out, encoding="utf-8"))
    failed = 0
    for r in report["results"]:
        failed += not r["ok"]
        print("%s  %s%s" % ("PASS" if r["ok"] else "FAIL", r["name"], "  -- " + r["detail"] if r["detail"] and (not r["ok"] or r["name"] in ("python host", "live answer has text", "chats listed")) else ""))
    print("\n%d checks, %d failed" % (len(report["results"]), failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
