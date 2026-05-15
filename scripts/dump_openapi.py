"""Dump the FastAPI OpenAPI schema to ``frontend/openapi.json``.

This is a build-time helper used by the frontend's
``npm run generate:api-types`` script. The schema is the canonical
backend contract — the frontend's generated DTO types and e2e
fixtures are validated against it so any shape drift surfaces at
``tsc`` time instead of at runtime.

The script avoids pulling in side-effectful imports from
``backend.app.main`` (database, redis, telegram bot setup) by
populating the minimal env vars FastAPI needs to construct the route
table. No database connections are opened — only the OpenAPI graph
is serialised.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent

    # Defaults are enough to import the app: the lifespan hook is not
    # invoked, so DB / Redis are never touched. We only need values
    # that satisfy ``Settings`` validation.
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://garant:garant@localhost/garant",
    )
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "0:openapi-dump")

    sys.path.insert(0, str(repo_root))
    # Late import: env vars must be set first.
    from backend.app.main import app  # noqa: E402

    schema = app.openapi()
    out_path = repo_root / "frontend" / "openapi.json"
    out_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {out_path.relative_to(repo_root)} ({len(json.dumps(schema))} bytes)")


if __name__ == "__main__":
    main()
