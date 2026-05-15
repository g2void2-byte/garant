"""R1 / C-3 — SPA fallback must not serve files outside ``frontend/dist``.

The catch-all SPA route forwards any unmatched GET to the
frontend's ``index.html``. Without normalisation it would also
happily serve ``/etc/passwd`` if the client sent ``../../../etc/passwd``.

We don't build the frontend bundle in CI's pytest job, so we test the
extracted ``resolve_spa_path`` helper directly with a tmp dist that
mimics the real layout. The route handler itself is a one-liner over
this helper, so unit-testing the helper covers the contract.
"""

from __future__ import annotations

import pathlib

from backend.app.main import resolve_spa_path


def _build_fake_dist(root: pathlib.Path) -> pathlib.Path:
    """Materialise a minimal dist layout for the resolver to walk."""
    dist = root / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=app></div>")
    (dist / "favicon.ico").write_bytes(b"\x00")
    (dist / "assets" / "app.js").write_text("console.log('hi')")
    return dist


def test_real_file_inside_dist_is_served(tmp_path: pathlib.Path):
    dist = _build_fake_dist(tmp_path)
    assert resolve_spa_path("favicon.ico", dist) == (dist / "favicon.ico").resolve()
    assert resolve_spa_path("assets/app.js", dist) == (dist / "assets" / "app.js").resolve()


def test_missing_route_falls_back_to_index_html(tmp_path: pathlib.Path):
    """Client-side routes (e.g. ``/deals/123``) don't exist on disk —
    the SPA shell handles them. The resolver must return ``index.html``."""
    dist = _build_fake_dist(tmp_path)
    assert resolve_spa_path("deals/123", dist) == dist / "index.html"
    assert resolve_spa_path("not-real-page", dist) == dist / "index.html"


def test_dotdot_segments_dont_escape_dist(tmp_path: pathlib.Path):
    """``../../etc/passwd`` resolves outside dist → must return index.html
    (the SPA shell) and NOT the resolved out-of-tree file."""
    dist = _build_fake_dist(tmp_path)
    # A file we'd target if traversal succeeded.
    outside = tmp_path / "secret.txt"
    outside.write_text("SECRET")

    result = resolve_spa_path("../secret.txt", dist)
    assert result == dist / "index.html"
    assert result.read_text().startswith("<!doctype html>")


def test_deeply_nested_traversal_is_blocked(tmp_path: pathlib.Path):
    """A long ``../../../../../../etc/passwd``-style path also blocks."""
    dist = _build_fake_dist(tmp_path)
    result = resolve_spa_path("../../../../../etc/passwd", dist)
    assert result == dist / "index.html"


def test_absolute_path_segment_is_blocked(tmp_path: pathlib.Path):
    """If the path starts with ``/`` the ``Path / "/foo"`` operator
    returns the absolute ``/foo`` and ``resolve()`` lands at ``/foo``
    — outside dist. Must fall back to index.html."""
    dist = _build_fake_dist(tmp_path)
    assert resolve_spa_path("/etc/passwd", dist) == dist / "index.html"


def test_empty_path_serves_index_html(tmp_path: pathlib.Path):
    """``GET /`` (empty path under the catch-all) → SPA shell."""
    dist = _build_fake_dist(tmp_path)
    assert resolve_spa_path("", dist) == dist / "index.html"


def test_directory_inside_dist_does_not_serve_directory(tmp_path: pathlib.Path):
    """A path that resolves to a real directory (``assets/``) but not a
    file must fall back to index.html — we don't want to ``FileResponse``
    a directory and 500 the request."""
    dist = _build_fake_dist(tmp_path)
    assert resolve_spa_path("assets", dist) == dist / "index.html"
