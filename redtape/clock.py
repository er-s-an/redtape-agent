"""One injectable clock for the product surfaces.

mockgov has MOCKGOV_TODAY; the web app and the daemon share REDTAPE_TODAY so a
demo run after midnight plans against the same "today" everywhere. Unset =
host date.
"""
from __future__ import annotations

import os
from datetime import date


def today() -> date:
    env = os.environ.get("REDTAPE_TODAY")
    return date.fromisoformat(env) if env else date.today()
