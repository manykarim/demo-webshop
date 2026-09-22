"""The login token's expiry names an unambiguous UTC instant (story API-007 AC-2).

``POST /api/auth/login`` used to return ``expires_at`` as a naive datetime
(``2026-09-21T23:52:03.537900``), which ISO 8601 reads as local time of an
unstated zone, so a consumer could not compare it with the current UTC time.
It is now an aware UTC value with the ``Z`` designator. The field name, its
position and the digits of the timestamp are unchanged, so parsers that ignore
the designator read the same value as before.
"""
from __future__ import annotations

import datetime as dt

JAMIE = {"email": "jamie@flowlinesupply.com", "password": "demo123"}


def test_expires_at_is_four_hours_from_now_in_utc(seeded_app_client) -> None:
    before = dt.datetime.now(dt.UTC)
    response = seeded_app_client.post("/api/auth/login", json=JAMIE)
    after = dt.datetime.now(dt.UTC)

    assert response.status_code == 200, response.text
    raw = response.json()["expires_at"]
    assert raw.endswith("Z"), f"expires_at {raw!r} carries no UTC designator"
    expires = dt.datetime.fromisoformat(raw)
    assert expires.utcoffset() == dt.timedelta(0)
    assert before + dt.timedelta(hours=4) <= expires <= after + dt.timedelta(hours=4)
