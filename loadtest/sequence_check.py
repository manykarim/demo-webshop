"""Scripted single-user check of preset composition and request naming.

A deterministic companion to ``locustfile.py``: one user walks a fixed
sequence of preset switches and checks, with the same expected-flag helpers
and the same ``leak:`` reporting, and quits when the sequence is done::

    uv run --group loadtest locust -f loadtest/sequence_check.py --headless \
        -H http://localhost:9090 -u 1 -r 1 --csv reports/sequence

The sequence is ``clean`` -> ``stage3`` -> ``buggy`` -> status (``v3``) ->
``stage2`` -> ``/products`` and ``GET /api/products/`` (both under their
``[slow-bug]`` names) -> status (``v2``) -> ``clean`` -> ``/products`` (without
the suffix). It shows what a random run only touches by chance: that presets
compose (``buggy`` keeps the stage, ``stage2`` keeps the bugs) and that the
slow-bug suffix follows the flag map rather than the last preset name.

It needs no orders, so unlike the load test it also runs against a target
without the native PDF libraries.
"""
from __future__ import annotations

import sys
from pathlib import Path

from locust import constant, task

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locustfile import (  # noqa: E402  (after the sys.path line above)
    NAME_PRODUCTS,
    WorkshopSpaceUser,
    expected_locator_stage,
    request_name,
    slow_bug_active,
)

#: ``(preset, expected stage after it, expected slow bug after it)``.
SEQUENCE = (
    ("stage3", "v3", False),
    ("buggy", "v3", True),
    ("stage2", "v2", True),
    ("clean", "v1", False),
)


class SequenceCheckUser(WorkshopSpaceUser):
    """One user, one scripted pass, then the run ends."""

    wait_time = constant(0)

    @task
    def run_sequence(self) -> None:
        # on_start already applied `clean` in this user's own space.
        self.check_expectation("clean", "v1", False)
        for preset, stage, slow in SEQUENCE:
            self.apply_preset(preset)
            self.check_expectation(preset, stage, slow)
            if preset in ("stage2", "clean"):
                # Naming after a preset that does not touch the bug flags:
                # `[slow-bug]` after `stage2`, plain again after `clean`.
                self.browse_catalogue()
            if preset in ("buggy", "stage2"):
                self.check_status(expected_stage=stage)
        self.environment.runner.quit()

    def check_expectation(self, preset: str, stage: str, slow: bool) -> None:
        """Compare the derived expectation with the scripted one.

        A mismatch means the helpers, not the server, are wrong, so it is
        reported under its own name and never as a ``leak:`` row.
        """
        derived_stage = expected_locator_stage(self.expected_flags)
        derived_slow = slow_bug_active(self.expected_flags)
        if (derived_stage, derived_slow) != (stage, slow):
            self.environment.events.request.fire(
                request_type="CHECK",
                name="sequence:expectation",
                response_time=0,
                response_length=0,
                context={},
                exception=AssertionError(
                    f"after {preset}: expected map says stage {derived_stage!r} and "
                    f"slow bug {derived_slow}, the script expects {stage!r} and {slow}"
                ),
            )

    def browse_catalogue(self) -> None:
        """Product page and catalogue API under their current names."""
        page_name = request_name(NAME_PRODUCTS, self.expected_flags)
        html = self.get_page("/products", page_name)
        self.check_indicator(html, page_name)
        self.fetch_assets(html, "/products")
        self.fetch_catalogue()
