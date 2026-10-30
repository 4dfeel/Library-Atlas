"""The login browser, run as its own process: python -m app.adapters.dlsite.browser

Protocol, JSON lines. stdin: first the request (which may hold the password), then
commands. stdout: events, the last one being the result (which holds the session).
Nothing secret travels by argument, environment or file, and nothing is ever logged:
the parent discards stderr.

The window stays hidden unless the platform needs the user, or the user chose web login.
"""

import json
import sys
import threading
import time
from typing import Any

from app.adapters.dlsite.login_page import (
    INSPECT_SCRIPT,
    LOGIN_URL,
    PageKind,
    VerificationGate,
    classify,
    is_login_page,
    page_state,
)

LOAD_TIMEOUT = 30.0
SUBMIT_TIMEOUT = 30.0
USER_TIMEOUT = 300.0
VERIFICATION_GRACE = 6.0
POLL = 0.4
# Pages that hold the cookies Atlas needs later. Visited only after a successful login.
COOKIE_PAGES = ("https://www.dlsite.com/home/", "https://play.dlsite.com/login/")

# Sets values the way a person typing would, then submits with the page's own button. The
# address is checked again inside the page, right before the password is written.
FILL_SCRIPT = """(function (values) {
  if (location.hostname !== 'login.dlsite.com' || location.pathname !== '/login')
    return 'wrong_page';
  var form = document.querySelector('form input[name=password]').form;
  var set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  [['login_id', values.login_id], ['password', values.password]].forEach(function (pair) {
    var input = form.querySelector('input[name=' + pair[0] + ']');
    set.call(input, pair[1]);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  window.__atlasSubmitted = true;
  var button = form.querySelector('button[type=submit], input[type=submit]');
  if (button) form.requestSubmit(button); else form.requestSubmit();
  return 'ok';
})(%s)"""


class _Output:
    def __init__(self) -> None:
        self._stream = sys.stdout.buffer
        self._lock = threading.Lock()
        self.finished = False
        sys.stdout = sys.stderr  # Nothing else may write to the protocol stream.

    def event(self, **fields: Any) -> None:
        with self._lock:
            if self.finished:
                return
            self.finished = fields.get("event") == "result"
            try:
                self._stream.write(json.dumps(fields, ensure_ascii=False).encode() + b"\n")
                self._stream.flush()
            except OSError:
                pass


def _inspect(window: Any) -> Any:
    try:
        raw = window.evaluate_js(INSPECT_SCRIPT)
        return page_state(json.loads(raw)) if raw else None
    except Exception:  # noqa: BLE001 - the page may be navigating; the next poll retries.
        return None


def _collect_cookies(window: Any) -> list[dict[str, Any]]:
    collected: dict[tuple[str, str, str], dict[str, Any]] = {}

    def take() -> None:
        for jar in window.get_cookies() or []:
            for name, morsel in jar.items():
                entry = {
                    "name": name,
                    "value": morsel.value,
                    "domain": morsel["domain"],
                    "path": morsel["path"] or "/",
                    "secure": bool(morsel["secure"]),
                }
                collected[(name, entry["domain"], entry["path"])] = entry

    take()
    for url in COOKIE_PAGES:
        window.load_url(url)
        deadline = time.monotonic() + LOAD_TIMEOUT
        while time.monotonic() < deadline:
            state = _inspect(window)
            if state and state.ready == "complete":
                break
            time.sleep(POLL)
        take()
    return list(collected.values())


def _drive(window: Any, request: dict[str, Any], output: _Output, state: dict[str, bool]) -> None:
    credentials = request["mode"] == "credentials"
    submitted = False
    revealed = not credentials
    deadline = time.monotonic() + (LOAD_TIMEOUT if credentials else USER_TIMEOUT)

    gate = VerificationGate(VERIFICATION_GRACE)
    asked = False

    def need_user() -> None:
        # Once only: the user gets one full timeout, not one that restarts on every poll.
        nonlocal revealed, deadline, asked
        if asked:
            return
        asked = True
        if not revealed:
            revealed = True
            window.show()
        deadline = time.monotonic() + USER_TIMEOUT
        output.event(event="state", state="needs_verification")

    while not output.finished:
        if time.monotonic() > deadline:
            output.event(event="result", outcome="timeout")
            break
        page = _inspect(window)
        if page is None:
            time.sleep(POLL)
            continue
        kind = classify(page, was_submitted=submitted)
        if gate.observe(verifying=kind is PageKind.VERIFICATION, now=time.monotonic()):
            need_user()
        if kind is PageKind.OFF_PLATFORM:
            window.load_url(LOGIN_URL)
        elif kind is PageKind.LOGIN_FORM and credentials and not submitted:
            if not (is_login_page(page.url) and page.has_token):
                output.event(event="result", outcome="form_changed")
                break
            values = {"login_id": request["login_id"], "password": request["password"]}
            outcome = window.evaluate_js(FILL_SCRIPT % json.dumps(values))
            del values
            request.pop("password", None)
            if outcome != "ok":
                output.event(event="result", outcome="form_changed")
                break
            submitted = True
            deadline = time.monotonic() + SUBMIT_TIMEOUT
            output.event(event="state", state="submitted")
        elif kind is PageKind.REJECTED:
            # One attempt per click. The user decides whether to try again.
            output.event(event="result", outcome="bad_credentials")
            break
        elif kind is PageKind.UNEXPECTED and credentials:
            output.event(event="result", outcome="form_changed")
            break
        elif kind is PageKind.LOGGED_IN:
            state["collecting"] = True
            if revealed:
                window.hide()
            output.event(event="state", state="confirming")
            cookies = _collect_cookies(window)
            window.clear_cookies()
            output.event(event="result", outcome="success", cookies=cookies)
            break
        time.sleep(POLL)
    window.destroy()


def _commands(window: Any, output: _Output) -> None:
    for line in sys.stdin:
        try:
            command = json.loads(line).get("command")
        except ValueError:
            continue
        if command == "cancel":
            break
        if command == "reveal":
            window.show()
            window.restore()
    # Cancelled, or the service went away: never leave a window behind.
    output.event(event="result", outcome="cancelled")
    window.destroy()


def main() -> int:
    output = _Output()
    try:
        request = json.loads(sys.stdin.readline())
        import webview  # Heavy, and only ever loaded in this process.

        window = webview.create_window(
            "Library Atlas · DLsite 验证",
            LOGIN_URL,
            hidden=request["mode"] == "credentials",
            width=460,
            height=660,
            background_color="#0B0E14",
        )
        state = {"collecting": False}

        def on_closed() -> None:
            if not state["collecting"]:
                output.event(event="result", outcome="cancelled")

        assert window is not None
        window.events.closed += on_closed
        threading.Thread(target=_commands, args=(window, output), daemon=True).start()
        webview.start(
            _drive,
            (window, request, output, state),
            private_mode=True,
            storage_path=request["storage_path"],
            debug=False,
        )
    except Exception:  # noqa: BLE001 - reported as an outcome; details could hold page data.
        output.event(event="result", outcome="browser_unavailable")
        return 1
    output.event(event="result", outcome="cancelled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
