"""What the login page is showing, decided from page structure only. Pure, so it is tested
without a browser. Observed 2026-10-30: a form with `_token`, `login_id` and `password` on
login.dlsite.com/login. After-submit behavior is checked against a real login."""

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

LOGIN_URL = "https://login.dlsite.com/login?user=self"
LOGIN_HOST = "login.dlsite.com"
PLATFORM_SUFFIX = ".dlsite.com"
LOGGED_IN_MARK = "ログイン中"

# Reads structure only, never field values or account details. Evaluated in the page.
INSPECT_SCRIPT = """JSON.stringify({
  url: location.origin + location.pathname,
  ready: document.readyState,
  hasForm: !!document.querySelector('form input[name=login_id]')
    && !!document.querySelector('form input[name=password]'),
  hasToken: !!document.querySelector('form input[name=_token]'),
  challenge: !!document.querySelector(
    '#challenge-form, #cf-wrapper, .cf-turnstile, [name=cf-turnstile-response]'
  ) || /just a moment/i.test(document.title),
  captcha: !!document.querySelector(
    '.g-recaptcha, [data-sitekey], iframe[src*=recaptcha], iframe[src*=turnstile]'
  ),
  loggedInMark: document.body ? document.body.innerText.includes('ログイン中') : false,
  submitted: window.__atlasSubmitted === true
})"""


class PageKind(StrEnum):
    LOADING = "loading"
    LOGIN_FORM = "login_form"
    REJECTED = "rejected"  # The form came back after a submit.
    VERIFICATION = "verification"  # The user has to do something on the page.
    LOGGED_IN = "logged_in"
    UNEXPECTED = "unexpected"  # Not a page Atlas knows how to work with.
    OFF_PLATFORM = "off_platform"


@dataclass(frozen=True)
class PageState:
    url: str = ""
    ready: str = ""
    has_form: bool = False
    has_token: bool = False
    challenge: bool = False
    captcha: bool = False
    logged_in_mark: bool = False
    submitted: bool = False


def is_platform_url(url: str) -> bool:
    parts = urlsplit(url)
    host = parts.hostname or ""
    return parts.scheme == "https" and (host == "dlsite.com" or host.endswith(PLATFORM_SUFFIX))


def is_login_page(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname == LOGIN_HOST and parts.path == "/login"


def classify(state: PageState, *, was_submitted: bool) -> PageKind:
    """`was_submitted` is Atlas's own record; `state.submitted` marks the page it submitted
    from, so a page without the mark is the response to that submit."""
    if not state.url or state.ready != "complete":
        return PageKind.LOADING
    if not is_platform_url(state.url):
        return PageKind.OFF_PLATFORM
    if state.challenge or state.captcha:
        return PageKind.VERIFICATION
    parts = urlsplit(state.url)
    if parts.hostname != LOGIN_HOST:
        return PageKind.LOGGED_IN
    if state.has_form:
        if not was_submitted:
            return PageKind.LOGIN_FORM
        return PageKind.LOADING if state.submitted else PageKind.REJECTED
    if state.logged_in_mark:
        return PageKind.LOGGED_IN
    return PageKind.VERIFICATION if was_submitted else PageKind.UNEXPECTED


class VerificationGate:
    """Decides when the user really has to act. Pages pass through states that look like
    verification (the redirect after a submit, a challenge that solves itself), so the
    window only appears if the page is still asking after `grace` seconds."""

    def __init__(self, grace: float) -> None:
        self._grace = grace
        self._since: float | None = None

    def observe(self, *, verifying: bool, now: float) -> bool:
        if not verifying:
            self._since = None
            return False
        if self._since is None:
            self._since = now
        return now - self._since >= self._grace


def page_state(data: dict[str, object]) -> PageState:
    return PageState(
        url=str(data.get("url") or ""),
        ready=str(data.get("ready") or ""),
        has_form=bool(data.get("hasForm")),
        has_token=bool(data.get("hasToken")),
        challenge=bool(data.get("challenge")),
        captcha=bool(data.get("captcha")),
        logged_in_mark=bool(data.get("loggedInMark")),
        submitted=bool(data.get("submitted")),
    )
