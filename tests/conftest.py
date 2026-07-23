"""Suite-wide guard: keep the deploy `.env`'s request log out of test runs.

pytest runs from the repo root, where the deploy `.env` sets REQUEST_LOG_PATH;
pydantic-settings reads that file at `create_app()` time, so without this
override every TestClient request in the suite — fuzzing, forced 500s and all —
would be appended to the LIVE request log (and tripped the live log monitor the
first time it happened). A process env var outranks `.env`, and the empty
string reads as "disabled"; the middleware's own tests monkeypatch.setenv a tmp
path over this default.
"""

import os

os.environ.setdefault("REQUEST_LOG_PATH", "")
