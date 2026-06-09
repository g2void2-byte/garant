"""Audit regression checks for deterministic offset pagination ordering."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _compact(source: str) -> str:
    return re.sub(r"\s+", "", source)


def test_router_created_at_desc_lists_have_id_tie_breakers() -> None:
    """Every router list sorted by newest row must also sort by id.

    Offset/page pagination over ``created_at`` alone is not stable when
    several rows are inserted in one transaction or otherwise share the
    same timestamp. A secondary ``id desc`` keeps page boundaries
    deterministic and prevents duplicate/missing rows between page 1/2.
    """
    offenders: list[str] = []
    pattern = re.compile(
        r"order_by\(\s*([A-Za-z_][A-Za-z0-9_]*)\.created_at\.desc\(\)\s*\)"
    )
    for path in sorted((REPO_ROOT / "backend" / "app" / "routers").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in pattern.finditer(source):
            rel = path.relative_to(REPO_ROOT).as_posix()
            offenders.append(f"{rel}: {match.group(0)}")

    assert offenders == []


def test_admin_users_sort_modes_have_stable_id_tie_breakers() -> None:
    source = _compact(_read("backend/app/routers/admin/users.py"))

    assert '"created_desc":(User.created_at.desc(),User.id.desc())' in source
    assert '"created_asc":(User.created_at.asc(),User.id.asc())' in source
    assert '"deals":(User.deals_total.desc(),User.id.desc())' in source
    assert (
        '"rating":(func.coalesce(User.rating_manual,0).desc(),'
        'User.good.desc(),User.id.desc(),)'
    ) in source
