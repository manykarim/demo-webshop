"""Live check harness of the acceptance-conformance suite (design D3).

**Target.** The only target selector is pytest-base-url's ``--base-url`` option
(``drift-coverage`` Decision 8); ``base_url`` is never set in the ini file and
this file reads no environment variable of its own that names a target. The
session-scoped ``base_url`` fixture below overrides pytest-base-url's inside
this directory: it returns the option when given and ``None`` otherwise, and it
refuses any host other than ``localhost``, ``127.0.0.1`` and ``::1`` unless
``CONFORMANCE_ALLOW_REMOTE=1`` is set - before any live fixture or browser
context exists, so no request is ever sent to a refused host. Without the
option nothing is started: the first live fixture (``target``) raises a usage
error naming ``--base-url``, so a run never falls back to whatever happens to
listen on the shop's usual port.

**Spaces** (``CONFORMANCE_SPACE_MODE=per-check|default``, default ``per-check``).
``space`` gives every check a fresh, verified clean state: reset, preset
``clean``, the variant's own step, then a precondition read from
``/api/workshop/status``; teardown resets again. In ``per-check`` mode every
check gets its own space ``cf-<run id>-<counter>`` and every request carries
``X-Workshop-Space``; in ``default`` mode no space header is sent, the target is
checked once before the first reset, and runs must be serial.

**Variants and sweep mode.** ``pytest_generate_tests`` parametrizes the
``variant`` of every check that uses ``space``: ``clean`` always; ``stage2`` to
``stage4`` and ``drift_and_bug`` for checks that use ``space_page``; one variant
per ``planted_bug`` flag, expected to fail with an ``AssertionError``
(``xfail(strict=True, raises=AssertionError)``), like ``drift_and_bug`` where
the check's flags meet that preset's bugs. ``CONFORMANCE_SWEEP_FLAG=<FLAG>`` or
``CONFORMANCE_SWEEP_PRESET=<preset>`` replaces all of them by one run per check
with that flag or preset applied after ``clean`` and no xfail.

**Harness failures are never assertions.** Every fixture here signals setup,
precondition and teardown failures with ``ConformanceSetupError`` (or
``pytest.UsageError`` for a misconfigured invocation) and never with a Python
or Playwright assertion: the xfail mark of a planted-bug variant also covers
the setup and teardown phases, and would report such a failure as XFAIL.

**Report.** A small plugin at the end aggregates the results per ``ac``
criterion into ``conformance-report/<space mode>/report.json`` and
``report.md``, prints a terminal summary and adds each criterion as the JUnit
property ``criterion``.

Shared harness rules (``reproducible-image`` D11): suite fixtures only, none
with a canonical harness name, no environment variable set for the pytest
process, and nothing from ``backend.app`` imported at module level - the
planted-bug registry, the presets and the space pattern are imported inside
the functions that need them.
"""
from __future__ import annotations

import datetime as dt
import functools
import itertools
import json
import os
import secrets
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from .helpers import ConformanceSetupError

HERE = Path(__file__).resolve().parent

SPACE_HEADER = "X-Workshop-Space"
SESSION_HEADER = "X-Session-ID"
SESSION_COOKIE = "session_id"
DEFAULT_SPACE = "default"

SPACE_MODE_ENV = "CONFORMANCE_SPACE_MODE"
PER_CHECK = "per-check"
DEFAULT_MODE = "default"
SPACE_MODES = (PER_CHECK, DEFAULT_MODE)
ALLOW_REMOTE_ENV = "CONFORMANCE_ALLOW_REMOTE"
SWEEP_FLAG_ENV = "CONFORMANCE_SWEEP_FLAG"
SWEEP_PRESET_ENV = "CONFORMANCE_SWEEP_PRESET"
XDIST_WORKER_ENV = "PYTEST_XDIST_WORKER"

#: Hosts a run may target without ``CONFORMANCE_ALLOW_REMOTE=1``.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
#: Timeout of every request the harness and the ``api`` client send.
REQUEST_TIMEOUT = 10.0
#: Flags no preset owns (``drift-coverage`` Decision 12); the clean state needs them off.
UNOWNED_FLAGS = ("NEW_CART_UI", "MOBILE_UI_V1", "SEARCH_V2")
#: Stage presets of the UI checks, with the stage each one selects.
STAGE_PRESETS = {"stage2": "v2", "stage3": "v3", "stage4": "v4"}
DRIFT_AND_BUG = "drift_and_bug"
CLEAN_PRESET = "clean"

REPORT_DIR = "conformance-report"


# ---------------------------------------------------------------------------
# Invocation settings
# ---------------------------------------------------------------------------


def space_mode() -> str:
    """The space mode of this run; any value but the two modes is a usage error."""
    value = os.environ.get(SPACE_MODE_ENV, "").strip() or PER_CHECK
    if value not in SPACE_MODES:
        raise pytest.UsageError(
            f"{SPACE_MODE_ENV}={value!r} is not a space mode; use {' or '.join(SPACE_MODES)} (default {PER_CHECK})"
        )
    return value


@functools.cache
def _presets() -> dict[str, dict[str, bool]]:
    from backend.app.core.workshop import build_presets

    return build_presets()


@functools.cache
def _registry_flags() -> tuple[str, ...]:
    from backend.app.core.workshop import PLANTED_BUGS

    return tuple(bug.flag for bug in PLANTED_BUGS)


def _bugs_of(flags: Mapping[str, bool]) -> frozenset[str]:
    return frozenset(flag for flag in _registry_flags() if flags.get(flag))


def _drift_and_bug_bugs() -> frozenset[str]:
    """The bug set preset ``drift_and_bug`` enables."""
    return _bugs_of(_presets()[DRIFT_AND_BUG])


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Variant:
    """One state a check runs in: what is applied after ``clean`` and what status must show.

    ``preset`` is applied through ``POST /api/workshop/preset``; ``flag`` is
    enabled through ``POST /api/workshop/flags``. ``stage`` and ``bugs`` are the
    ``locator_stage`` and ``active_bugs`` the precondition requires.
    ``expect_failure`` marks the variant ``xfail(strict=True, raises=AssertionError)``.
    """

    name: str
    preset: str | None = None
    flag: str | None = None
    stage: str = "v1"
    bugs: frozenset[str] = frozenset()
    expect_failure: bool = False
    sweep: bool = False


CLEAN = Variant(CLEAN_PRESET)


def _sweep_settings() -> tuple[str | None, str | None]:
    flag = os.environ.get(SWEEP_FLAG_ENV, "").strip() or None
    preset = os.environ.get(SWEEP_PRESET_ENV, "").strip() or None
    return flag, preset


def validate_invocation() -> None:
    """Stop the run on a misconfigured space mode or sweep setting."""
    space_mode()
    flag, preset = _sweep_settings()
    if flag and preset:
        raise pytest.UsageError(f"set at most one of {SWEEP_FLAG_ENV} and {SWEEP_PRESET_ENV}")
    if flag and flag not in _registry_flags():
        raise pytest.UsageError(
            f"{SWEEP_FLAG_ENV}={flag} names no registered planted bug; registered: {', '.join(_registry_flags())}"
        )
    if preset and preset not in _presets():
        raise pytest.UsageError(
            f"{SWEEP_PRESET_ENV}={preset} names no workshop preset; presets: {', '.join(_presets())}"
        )


def sweep_variant() -> Variant | None:
    """The one variant of sweep mode, or ``None`` outside it (or when misconfigured)."""
    flag, preset = _sweep_settings()
    if flag and not preset and flag in _registry_flags():
        return Variant(f"sweep-{flag}", flag=flag, bugs=frozenset({flag}), sweep=True)
    if preset and not flag and preset in _presets():
        from backend.app.core.workshop import effective_stage

        flags = {**_presets()[CLEAN_PRESET], **_presets()[preset]}
        return Variant(
            f"sweep-{preset}",
            preset=preset,
            stage=f"v{effective_stage(flags)}",
            bugs=_bugs_of(flags),
            sweep=True,
        )
    return None


def _xfail(variant: Variant) -> pytest.MarkDecorator:
    return pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason=f"[{variant.name}] a planted bug of this check is enabled; the check must fail with an assertion",
    )


def variants_for(flags: Sequence[str], drives_page: bool) -> list[Variant]:
    """The variants of a check with ``planted_bug`` ``flags`` (task 4.4)."""
    swept = sweep_variant()
    if swept is not None:
        return [swept]
    variants = [CLEAN]
    if drives_page:
        variants += [Variant(name, preset=name, stage=stage) for name, stage in STAGE_PRESETS.items()]
        bugs = _drift_and_bug_bugs()
        variants.append(
            Variant(DRIFT_AND_BUG, preset=DRIFT_AND_BUG, stage="v4", bugs=bugs, expect_failure=bool(bugs & set(flags)))
        )
    variants += [Variant(flag, flag=flag, bugs=frozenset({flag}), expect_failure=True) for flag in flags]
    return variants


def _planted_bug_flags(node: Any) -> list[str]:
    flags: list[str] = []
    for marker in node.iter_markers("planted_bug"):
        for flag in marker.args:
            if flag not in flags:
                flags.append(flag)
    return flags


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "variant" not in metafunc.fixturenames:
        return
    variants = variants_for(_planted_bug_flags(metafunc.definition), "space_page" in metafunc.fixturenames)
    metafunc.parametrize(
        "variant",
        [
            pytest.param(variant, id=variant.name, marks=[_xfail(variant)] if variant.expect_failure else [])
            for variant in variants
        ],
    )


@pytest.fixture
def variant() -> Variant:
    """The variant of the running check; replaced by the parametrization above."""
    return CLEAN


# ---------------------------------------------------------------------------
# Target
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def base_url(pytestconfig: pytest.Config) -> str | None:
    """The ``--base-url`` option, or ``None``; refuses non-loopback hosts.

    Overrides pytest-base-url's fixture of the same name inside this directory,
    session-scoped because pytest-playwright's ``browser_context_args`` needs it.
    """
    value = pytestconfig.getoption("base_url")
    if not value:
        return None
    host = (urlsplit(value).hostname or "").lower()
    if not host:
        raise pytest.UsageError(f"--base-url {value!r} has no host; pass a full URL such as http://localhost:<port>")
    if host not in LOOPBACK_HOSTS and os.environ.get(ALLOW_REMOTE_ENV) != "1":
        raise pytest.UsageError(
            f"--base-url {value} targets the non-loopback host {host!r}. The conformance checks create spaces, "
            f"carts and orders and reset flags; run them against a locally started image, or set "
            f"{ALLOW_REMOTE_ENV}=1 to target this host on purpose."
        )
    return value


@dataclass(frozen=True)
class Target:
    """The running image under test, as ``/health`` described it once per session."""

    base_url: str
    version: str | None
    health: Mapping[str, Any]


def _json(response: httpx.Response, what: str) -> Any:
    try:
        return response.json()
    except ValueError as error:
        raise ConformanceSetupError(f"{what}: the response is not JSON: {response.text[:200]!r}") from error


@pytest.fixture(scope="session")
def target(base_url: str | None, pytestconfig: pytest.Config) -> Target:
    """The first live fixture: needs ``--base-url`` and reads ``/health`` once."""
    if not base_url:
        raise pytest.UsageError(
            "the conformance checks need a running shop image: pass --base-url with the URL of a locally "
            "started image, e.g. --base-url http://localhost:<port>. Nothing is started without it."
        )
    url = base_url.rstrip("/")
    try:
        response = httpx.get(f"{url}/health", timeout=REQUEST_TIMEOUT)
    except httpx.HTTPError as error:
        raise ConformanceSetupError(f"GET {url}/health failed: {error!r}") from error
    if response.status_code != 200:
        raise ConformanceSetupError(f"GET {url}/health answered {response.status_code}: {response.text[:200]!r}")
    health = _json(response, f"GET {url}/health")
    version = health.get("version") if isinstance(health, dict) else None
    _collector(pytestconfig).version = version
    return Target(url, version, health if isinstance(health, dict) else {})


# ---------------------------------------------------------------------------
# Spaces
# ---------------------------------------------------------------------------

#: The per-run id of ``per-check`` space names, and their counter.
RUN_ID = secrets.token_hex(3)
_SPACE_COUNTER = itertools.count(1)


def next_space_id() -> str:
    """``cf-<run id>-<counter>``, validated against the ``workshop-spaces`` handle pattern."""
    from backend.app.core.spaces import SPACE_PATTERN

    space_id = f"cf-{RUN_ID}-{next(_SPACE_COUNTER):04d}"
    if not SPACE_PATTERN.fullmatch(space_id):
        raise ConformanceSetupError(f"generated space id {space_id!r} is not a valid workshop space handle")
    return space_id


@dataclass
class Space:
    """The space a check runs in, with the harness calls that prepare it.

    ``id`` is the ``per-check`` space or ``default``; ``headers`` holds the
    ``X-Workshop-Space`` header in ``per-check`` mode and nothing in ``default``
    mode. Every method raises :class:`ConformanceSetupError` on failure.
    """

    id: str
    mode: str
    variant: Variant
    base_url: str
    headers: Mapping[str, str]
    client: httpx.Client = field(repr=False)

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """A harness request in this space; transport errors become setup errors."""
        try:
            return self.client.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            raise ConformanceSetupError(f"{method} {path} in space {self.id!r} failed: {error!r}") from error

    def _call(self, method: str, path: str, what: str, **kwargs: Any) -> Any:
        response = self.request(method, path, **kwargs)
        if response.status_code == 401 and self.mode == DEFAULT_MODE:
            raise ConformanceSetupError(
                f"{what} in the default space answered 401: the target runs with WORKSHOP_SHARED_MODE on, "
                f"which guards the default space; run default mode against a local image without it"
            )
        if response.status_code != 200:
            raise ConformanceSetupError(
                f"{what} in space {self.id!r} answered {response.status_code}: {response.text[:300]!r}"
            )
        return _json(response, what)

    def reset(self) -> dict[str, Any]:
        """``POST /api/workshop/reset``: this space's flags, carts and orders."""
        body = self._call("POST", "/api/workshop/reset", "POST /api/workshop/reset")
        if body.get("space") != self.id:
            raise ConformanceSetupError(f"reset acted on space {body.get('space')!r}, expected {self.id!r}")
        return body

    def apply_preset(self, preset: str) -> dict[str, Any]:
        body = self._call("POST", "/api/workshop/preset", f"preset {preset}", json={"preset": preset})
        if body.get("status") != "success":
            raise ConformanceSetupError(f"preset {preset} in space {self.id!r} did not succeed: {body!r}")
        return body

    def set_flags(self, flags: Mapping[str, bool]) -> dict[str, Any]:
        body = self._call("POST", "/api/workshop/flags", f"flags {dict(flags)}", json={"flags": dict(flags)})
        if body.get("status") != "success":
            raise ConformanceSetupError(f"flags {dict(flags)} in space {self.id!r} did not succeed: {body!r}")
        return body

    def status(self) -> dict[str, Any]:
        return self._call("GET", "/api/workshop/status", "GET /api/workshop/status")

    def check_precondition(self) -> dict[str, Any]:
        """The clean-state precondition of the variant (design D3 step 4)."""
        status = self.status()
        problems: list[str] = []
        if status.get("space") != self.id:
            problems.append(f"status reports space {status.get('space')!r}, expected {self.id!r}")
        if status.get("locator_stage") != self.variant.stage:
            problems.append(
                f"locator stage {status.get('locator_stage')} is active, the variant expects stage {self.variant.stage}"
            )
        active = set(status.get("active_bugs") or ())
        for flag in sorted(active - self.variant.bugs):
            problems.append(f"planted bug {flag} is active but not expected by the variant")
        for flag in sorted(self.variant.bugs - active):
            problems.append(f"planted bug {flag} is expected by the variant but not active")
        flags = status.get("all_flags") or {}
        for flag in UNOWNED_FLAGS:
            if flags.get(flag):
                problems.append(f"{flag} is enabled; the clean state needs it at its seeded default (off)")
        if problems:
            raise ConformanceSetupError(
                f"target not in the expected state for variant [{self.variant.name}] in space {self.id!r}: "
                + "; ".join(problems)
            )
        return status

    def prepare(self) -> dict[str, Any]:
        """Reset, preset ``clean``, the variant's own step, then the precondition."""
        self.reset()
        self.apply_preset(CLEAN_PRESET)
        if self.variant.preset:
            self.apply_preset(self.variant.preset)
        if self.variant.flag:
            self.set_flags({self.variant.flag: True})
        return self.check_precondition()


def open_space(target: Target, variant: Variant, request: pytest.FixtureRequest) -> Iterator[Space]:
    """The body of the ``space`` fixture, reusable by fixture overrides."""
    mode = space_mode()
    if mode == DEFAULT_MODE:
        if os.environ.get(XDIST_WORKER_ENV):
            raise pytest.UsageError(
                f"{SPACE_MODE_ENV}={DEFAULT_MODE} runs are serial: every check resets the shared default space; "
                f"run without parallel workers ({XDIST_WORKER_ENV}={os.environ[XDIST_WORKER_ENV]})"
            )
        request.getfixturevalue("_default_space_checked")
        space_id, headers = DEFAULT_SPACE, {}
    else:
        space_id = next_space_id()
        headers = {SPACE_HEADER: space_id}
    with httpx.Client(base_url=target.base_url, headers=headers, timeout=REQUEST_TIMEOUT) as client:
        space = Space(space_id, mode, variant, target.base_url, headers, client)
        space.prepare()
        yield space
        space.reset()


@pytest.fixture(scope="session")
def _default_space_checked(target: Target) -> dict[str, Any]:
    """``default`` mode: the target's default space is clean before the first reset.

    A default-space reset restores global flags, so it would silently repair a
    misconfigured target; this reads status once, before that, and fails the
    run instead.
    """
    try:
        response = httpx.get(f"{target.base_url}/api/workshop/status", timeout=REQUEST_TIMEOUT)
    except httpx.HTTPError as error:
        raise ConformanceSetupError(f"GET /api/workshop/status failed: {error!r}") from error
    if response.status_code != 200:
        raise ConformanceSetupError(f"GET /api/workshop/status answered {response.status_code}")
    status = _json(response, "GET /api/workshop/status")
    problems: list[str] = []
    for flag in status.get("active_bugs") or ():
        problems.append(f"planted bug {flag} is enabled")
    if status.get("locator_stage") != "v1":
        problems.append(f"locator stage {status.get('locator_stage')} is active, not v1")
    for flag in UNOWNED_FLAGS:
        if (status.get("all_flags") or {}).get(flag):
            problems.append(f"{flag} is enabled")
    if problems:
        raise ConformanceSetupError(
            "the default space is not in its clean state before the first reset of this run: "
            + "; ".join(problems)
            + ". A default-space reset would repair it silently, so the run stops instead."
        )
    return status


@pytest.fixture
def space(target: Target, variant: Variant, request: pytest.FixtureRequest) -> Iterator[Space]:
    """A verified clean state for one check, in the variant's configuration."""
    yield from open_space(target, variant, request)


@pytest.fixture
def api(space: Space) -> Iterator[httpx.Client]:
    """An ``httpx.Client`` on the target, in the check's space.

    Carries ``X-Workshop-Space`` in ``per-check`` mode only and has a 10-second
    timeout. ``X-Session-ID`` is never set here; a check passes it per request
    (``headers={"X-Session-ID": ...}``) where its criterion uses one.
    """
    with httpx.Client(base_url=space.base_url, headers=dict(space.headers), timeout=REQUEST_TIMEOUT) as client:
        yield client


@pytest.fixture
def space_page(space: Space, context: Any, page: Any) -> Any:
    """pytest-playwright's ``page`` (headless Chromium), in the check's space.

    In ``per-check`` mode the space header is set on the function-scoped
    ``context``, so every navigation and ``page.request`` call carries it.
    """
    if space.headers:
        context.set_extra_http_headers(dict(space.headers))
    return page


CartItem = int | tuple[int, int] | Mapping[str, Any]


@pytest.fixture
def prefill_cart(space: Space) -> Callable[[Any, Iterable[CartItem]], str]:
    """Arrange a cart through the API for a browser context.

    ``prefill_cart(context, items)`` generates a session id, sets it as the
    ``session_id`` cookie of the base URL on ``context`` and posts every item to
    ``/api/cart/items`` with the same ``X-Session-ID``, in the check's space.
    An item is a product id, a ``(product_id, quantity)`` pair or a request
    body. Returns the session id.
    """

    def prefill(context: Any, items: Iterable[CartItem]) -> str:
        session_id = f"cf-session-{secrets.token_hex(8)}"
        context.add_cookies([{"name": SESSION_COOKIE, "value": session_id, "url": space.base_url}])
        for item in items:
            if isinstance(item, Mapping):
                body = dict(item)
            elif isinstance(item, tuple):
                body = {"product_id": item[0], "quantity": item[1]}
            else:
                body = {"product_id": item, "quantity": 1}
            response = space.request("POST", "/api/cart/items", json=body, headers={SESSION_HEADER: session_id})
            if response.status_code != 200:
                raise ConformanceSetupError(
                    f"prefilling the cart with {body} answered {response.status_code}: {response.text[:200]!r}"
                )
        return session_id

    return prefill


# ---------------------------------------------------------------------------
# Report plugin (task 4.5)
# ---------------------------------------------------------------------------


@dataclass
class _Run:
    """What the report knows about one collected conformance check (one variant)."""

    nodeid: str
    check: str
    criteria: tuple[str, ...]
    variant: Variant | None
    phases: dict[str, tuple[str, bool]] = field(default_factory=dict)
    setup_error_in_call: bool = False

    @property
    def expected(self) -> str:
        return "xfail" if self.variant is not None and self.variant.expect_failure else "pass"

    @property
    def outcome(self) -> str:
        """``passed``, ``failed``, ``xfailed``, ``skipped`` or ``error``."""
        setup = self.phases.get("setup")
        call = self.phases.get("call")
        teardown = self.phases.get("teardown")
        if (setup and setup[0] == "failed") or (teardown and teardown[0] == "failed"):
            return "error"
        if setup and setup[0] == "skipped":
            return "xfailed" if setup[1] else "skipped"
        if call is None:
            return "error"
        if call[0] == "failed":
            return "error" if self.setup_error_in_call else "failed"
        if call[0] == "skipped":
            return "xfailed" if call[1] else "skipped"
        return "passed"

    @property
    def result(self) -> str:
        """``pass`` when the variant behaved as expected, else ``fail`` or ``error``."""
        outcome = self.outcome
        if outcome in ("error", "skipped"):
            return "error"
        wanted = "xfailed" if self.expected == "xfail" else "passed"
        return "pass" if outcome == wanted else "fail"


@dataclass
class _Collector:
    runs: dict[str, _Run] = field(default_factory=dict)
    version: str | None = None
    started: float | None = None
    finished: float | None = None
    report_dir: Path | None = None
    summary: dict[str, Any] | None = None


_COLLECTOR_KEY = pytest.StashKey[_Collector]()


def _collector(config: pytest.Config) -> _Collector:
    collector = config.stash.get(_COLLECTOR_KEY, None)
    if collector is None:
        collector = _Collector()
        config.stash[_COLLECTOR_KEY] = collector
    return collector


def _in_suite(item: pytest.Item) -> bool:
    try:
        return Path(str(item.path)).resolve().is_relative_to(HERE)
    except (OSError, ValueError):
        return False


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items: list[pytest.Item]) -> None:
    """After ``-m``/``-k`` deselection: validate the invocation and label the selected checks."""
    suite_items = [item for item in items if _in_suite(item) and item.get_closest_marker("conformance")]
    if not suite_items:
        return
    validate_invocation()
    collector = _collector(config)
    for item in suite_items:
        criteria = tuple(arg for marker in item.iter_markers("ac") for arg in marker.args)
        callspec = getattr(item, "callspec", None)
        variant = callspec.params.get("variant") if callspec is not None else None
        collector.runs[item.nodeid] = _Run(
            nodeid=item.nodeid,
            check=item.nodeid.split("[", 1)[0],
            criteria=criteria,
            variant=variant if isinstance(variant, Variant) else None,
        )
        for criterion in criteria:
            item.user_properties.append(("criterion", criterion))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Iterator[Any]:
    """Record each phase of a conformance check, as the final report shows it.

    Registered after pytest's own xfail handling, so this wrapper encloses it
    and sees the outcome with ``wasxfail`` already applied.
    """
    report = yield
    collector = _collector(item.config)
    run = collector.runs.get(item.nodeid)
    if run is not None:
        run.phases[report.when] = (report.outcome, getattr(report, "wasxfail", None) is not None)
        if call.when == "call" and call.excinfo is not None:
            run.setup_error_in_call = call.excinfo.errisinstance(ConformanceSetupError)
        collector.started = call.start if collector.started is None else min(collector.started, call.start)
        collector.finished = call.stop if collector.finished is None else max(collector.finished, call.stop)
    return report


def _criterion_key(criterion: str) -> tuple[str, int, str]:
    story, _, number = criterion.partition("_AC-")
    return (story, int(number), "") if number.isdigit() else ("~", 0, criterion)


def _worst(results: Iterable[str]) -> str:
    results = list(results)
    for result in ("error", "fail"):
        if result in results:
            return result
    return "pass"


def _variant_label(run: _Run) -> str:
    name = run.variant.name if run.variant is not None else "-"
    return name if run.result == "pass" else f"{name} ({run.result})"


def build_report(config: pytest.Config) -> dict[str, Any] | None:
    """The per-criterion report of the checks that ran, or ``None`` if none ran."""
    collector = _collector(config)
    runs = [run for run in collector.runs.values() if run.phases]
    if not runs:
        return None
    criteria: dict[str, list[_Run]] = {}
    harness: list[_Run] = []
    for run in runs:
        if run.criteria:
            for criterion in run.criteria:
                criteria.setdefault(criterion, []).append(run)
        else:
            harness.append(run)

    flag, preset = _sweep_settings()
    started = collector.started or time.time()
    finished = collector.finished or started
    rows = []
    for criterion in sorted(criteria, key=_criterion_key):
        items = criteria[criterion]
        rows.append(
            {
                "criterion": criterion,
                "result": _worst(run.result for run in items),
                "checks": sorted({run.check for run in items}),
                "variants": [_variant_label(run) for run in items],
                "runs": [
                    {
                        "check": run.nodeid,
                        "variant": run.variant.name if run.variant else None,
                        "expected": run.expected,
                        "outcome": run.outcome,
                        "result": run.result,
                    }
                    for run in items
                ],
            }
        )
    harness_rows = [
        {"check": run.nodeid, "expected": run.expected, "outcome": run.outcome, "result": run.result}
        for run in sorted(harness, key=lambda run: run.nodeid)
    ]
    counts = {result: sum(1 for row in rows if row["result"] == result) for result in ("pass", "fail", "error")}
    harness_counts = {
        result: sum(1 for row in harness_rows if row["result"] == result) for result in ("pass", "fail", "error")
    }
    return {
        "base_url": config.getoption("base_url"),
        "space_mode": os.environ.get(SPACE_MODE_ENV, "").strip() or PER_CHECK,
        "version": collector.version,
        "run": {
            "started": dt.datetime.fromtimestamp(started, dt.UTC).isoformat(timespec="seconds"),
            "finished": dt.datetime.fromtimestamp(finished, dt.UTC).isoformat(timespec="seconds"),
            "duration_seconds": round(finished - started, 1),
        },
        "sweep": {"flag": flag} if flag else {"preset": preset} if preset else None,
        "summary": {"criteria": counts, "harness": harness_counts},
        "criteria": rows,
        "harness": harness_rows,
    }


def _markdown(report: Mapping[str, Any]) -> str:
    sweep = report["sweep"]
    lines = [
        "# Conformance report",
        "",
        f"- Base URL: {report['base_url']}",
        f"- Space mode: {report['space_mode']}",
        f"- Version (/health): {report['version']}",
        (
            f"- Run time: {report['run']['started']} to {report['run']['finished']} "
            f"({report['run']['duration_seconds']} s)"
        ),
        f"- Sweep: {next(iter(sweep.values())) if sweep else 'none'}",
        "",
        "Criterion results: "
        + ", ".join(f"{count} {result}" for result, count in report["summary"]["criteria"].items()),
        "",
        "## Criteria",
        "",
        "| Criterion | Result | Checks | Variants |",
        "|-----------|--------|--------|----------|",
    ]
    for row in report["criteria"]:
        lines.append(
            f"| {row['criterion']} | {row['result']} | {'<br>'.join(row['checks'])} | {', '.join(row['variants'])} |"
        )
    lines += ["", "## Harness", "", "| Check | Result | Outcome |", "|-------|--------|---------|"]
    for row in report["harness"]:
        lines.append(f"| {row['check']} | {row['result']} | {row['outcome']} |")
    return "\n".join(lines) + "\n"


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    report = build_report(config)
    if report is None:
        return
    directory = Path(config.rootpath) / REPORT_DIR / report["space_mode"]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (directory / "report.md").write_text(_markdown(report), encoding="utf-8")
    collector = _collector(config)
    collector.report_dir = directory
    collector.summary = report
    errors = report["summary"]["criteria"]["error"] + report["summary"]["harness"]["error"]
    failures = report["summary"]["criteria"]["fail"] + report["summary"]["harness"]["fail"]
    if (errors or failures) and session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    collector = _collector(config)
    report = collector.summary
    if report is None:
        return
    counts = report["summary"]["criteria"]
    terminalreporter.write_sep(
        "=",
        f"conformance: {report['space_mode']} mode, {len(report['criteria'])} criteria: "
        + ", ".join(f"{count} {result}" for result, count in counts.items()),
    )
    for row in report["criteria"]:
        if row["result"] != "pass":
            bad = [label for label in row["variants"] if "(" in label]
            terminalreporter.write_line(f"{row['result']}: {row['criterion']}  [{'; '.join(bad)}]")
    for row in report["harness"]:
        if row["result"] != "pass":
            terminalreporter.write_line(f"harness {row['result']}: {row['check']} ({row['outcome']})")
    terminalreporter.write_line(f"report: {collector.report_dir}/report.md")
