"""Acceptance-conformance suite (design D3 and D4 of `acceptance-conformance`).

Offline modules (story parser, locator helpers, coverage guard) run in every
``uv run pytest backend/tests``. The live checks carry the ``conformance``
marker, are deselected by default and need an explicit ``--base-url``.
"""
