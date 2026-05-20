"""L-19 regression test: ban redundant ``await session.refresh(obj)`` calls.

Background (see :mod:`backend.app.db` for the long version):

``async_sessionmaker(expire_on_commit=False)`` combined with SQLAlchemy
2.0 + asyncpg "eager defaults" RETURNING means an ORM instance is
already populated with every ``server_default``-backed column right
after ``await session.commit()`` finishes an INSERT — ``created_at``,
enum defaults, bigint counters, etc. ``UPDATE``\\s do NOT auto-fetch
``onupdate=`` values, but those are a small, enumerable set in this
codebase.

Plain ``await session.refresh(obj)`` post-commit is therefore
redundant under this configuration: it round-trips the DB to re-fetch
columns the ORM already has. The narrow form
``session.refresh(obj, attribute_names=[...])`` is fine — and required
in a handful of places where we genuinely need a fresh read of an
``onupdate=``-driven column or an unloaded relationship.

This test walks the backend AST, finds every ``session.refresh``
call site, and asserts that:

1. Every call passes the ``attribute_names=`` kwarg — no bare
   ``session.refresh(obj)``.
2. Every call site matches an entry in the explicit allowlist below
   (file + qualified function + the exact ``attribute_names`` list).
   New refresh calls require a deliberate audit + an allowlist update.

If a legitimate new refresh site appears, add it to ``ALLOWED_SITES``
below along with a one-line justification in the comment.
"""

from __future__ import annotations

import ast
import pathlib

# (file_relative_to_repo_root, qualified_function_name, refreshed_var,
#  sorted attribute_names tuple, rationale)
ALLOWED_SITES: frozenset[tuple[str, str, str, tuple[str, ...]]] = frozenset(
    {
        # ``credit_deposit`` re-reads ``status``/``paid_at`` under the
        # balance-row FOR UPDATE lock as belt-and-suspenders behind
        # the outer deposit-row lock both callers acquire. The
        # idempotency check that follows needs the *latest* value, so
        # the narrow refresh is the explicit "we want a fresh read".
        (
            "backend/app/services_wallet.py",
            "credit_deposit",
            "deposit",
            ("paid_at", "status"),
        ),
        # H-1 retired ``credit_invoice`` and the legacy USD
        # ``Invoice`` ledger; the matching allowlist entry is gone.
        # ``UserBalance.updated_at`` carries ``onupdate=func.now()``,
        # which is the one column eager-defaults RETURNING does NOT
        # populate after an UPDATE. The admin balance-adjust response
        # surfaces ``updated_at`` in the JSON payload, so we reload
        # just that column post-commit.
        (
            "backend/app/routers/admin/wallets.py",
            "adjust_user_balance",
            "bal",
            ("updated_at",),
        ),
        # ``update_me`` mutates the eager ``user.forums`` collection
        # via ``session.delete`` / ``session.add``. ``refresh`` without
        # ``attribute_names`` does not reload eager relationships, so
        # the cached collection could still reference just-deleted
        # ``Forum`` rows when the serializer iterates them. Reload
        # just the relationship.
        (
            "backend/app/routers/me.py",
            "update_me",
            "user",
            ("forums",),
        ),
        # ``create_service_comment`` inserts the comment then needs
        # to serialise it with its ``author``. ``expire_on_commit``
        # keeps the column attributes fresh and eager-defaults
        # RETURNING fills ``created_at``, but neither materialises
        # the relationship — reload just ``author``.
        (
            "backend/app/routers/services.py",
            "create_service_comment",
            "comment",
            ("author",),
        ),
        # ``create_deal`` builds a brand-new ``Deal`` from FK ids
        # (``buyer_id`` / ``seller_id`` / ``currency_id``) and never
        # SELECTs it back, so ``lazy="selectin"`` doesn't fire on the
        # commit path. The router-side serialiser ``_deal_out`` reads
        # ``deal.buyer.username`` / ``deal.seller.username`` /
        # ``deal.currency.code`` straight after this returns — without
        # the eager reload those accesses raise
        # ``MissingGreenlet`` from a sync lazy-load. ``accept_deal`` /
        # ``decline_deal`` / ``finish_deal`` / ``request_cancel`` /
        # ``revoke_cancel`` / ``accept_cancel`` / ``start_arbitration``
        # / ``resolve_arbitration`` all receive a ``Deal`` previously
        # SELECTed via ``_get_locked`` (which DID fire selectin), so
        # they keep the relationships in memory under
        # ``expire_on_commit=False`` and do NOT need a follow-up
        # refresh — only ``create_deal`` does.
        (
            "backend/app/services_deals.py",
            "create_deal",
            "deal",
            ("buyer", "currency", "seller"),
        ),
    }
)


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2]


def _backend_python_files() -> list[pathlib.Path]:
    return sorted((_repo_root() / "backend" / "app").rglob("*.py"))


class _RefreshCallVisitor(ast.NodeVisitor):
    """Collect every ``session.refresh(...)`` call in a module."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        # (qualified function name, lineno, refreshed-var name,
        #  sorted attribute_names tuple or None for the bare form)
        self.calls: list[tuple[str, int, str, tuple[str, ...] | None]] = []
        self._func_stack: list[str] = []

    def _enter_func(self, name: str) -> None:
        self._func_stack.append(name)

    def _leave_func(self) -> None:
        self._func_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter_func(node.name)
        self.generic_visit(node)
        self._leave_func()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._enter_func(node.name)
        self.generic_visit(node)
        self._leave_func()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # Method names inside a class become ``ClassName.method``.
        self._enter_func(node.name)
        for child in node.body:
            self.visit(child)
        self._leave_func()

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "refresh"
            and isinstance(func.value, ast.Name)
            and func.value.id == "session"
        ):
            if not node.args:
                # ``session.refresh()`` with no positional arg — illegal
                # at runtime but record it so the test surfaces the
                # offending file rather than crashing here.
                refreshed = "<missing>"
            else:
                first = node.args[0]
                refreshed = first.id if isinstance(first, ast.Name) else ast.unparse(first)

            attr_names: tuple[str, ...] | None = None
            for kw in node.keywords:
                if kw.arg == "attribute_names":
                    value = kw.value
                    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
                        items: list[str] = []
                        for elt in value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                items.append(elt.value)
                            else:
                                # Non-literal entry — record the raw
                                # source so the assertion message is
                                # actionable.
                                items.append(ast.unparse(elt))
                        attr_names = tuple(sorted(items))
                    else:
                        attr_names = (ast.unparse(value),)

            qualified = ".".join(self._func_stack) or "<module>"
            self.calls.append((qualified, node.lineno, refreshed, attr_names))

        self.generic_visit(node)


def _collect_refresh_sites() -> list[tuple[str, str, int, str, tuple[str, ...] | None]]:
    """Walk every backend file and return every ``session.refresh`` site.

    Returns a list of
    ``(rel_path, qualified_function, lineno, refreshed_var, attr_names)``
    tuples sorted by ``(rel_path, lineno)``.
    """
    repo = _repo_root()
    out: list[tuple[str, str, int, str, tuple[str, ...] | None]] = []
    for path in _backend_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _RefreshCallVisitor(path)
        visitor.visit(tree)
        rel = path.relative_to(repo).as_posix()
        for qualified, lineno, refreshed, attrs in visitor.calls:
            out.append((rel, qualified, lineno, refreshed, attrs))
    out.sort(key=lambda r: (r[0], r[2]))
    return out


def test_no_plain_session_refresh_post_commit() -> None:
    """Every ``session.refresh`` call MUST pass ``attribute_names=``."""
    sites = _collect_refresh_sites()
    plain = [
        (rel, qualified, lineno, refreshed)
        for rel, qualified, lineno, refreshed, attrs in sites
        if attrs is None
    ]
    assert not plain, (
        "Found bare ``await session.refresh(obj)`` call(s). With "
        "``expire_on_commit=False`` + SA 2.0 eager-defaults RETURNING, "
        "loaded columns are already fresh after commit and "
        "``server_default``s are RETURNed on INSERT — a plain refresh "
        "is a redundant DB round-trip. Use "
        "``session.refresh(obj, attribute_names=[...])`` if you "
        "genuinely need to reload an ``onupdate=`` column / "
        "relationship, then add the site to ALLOWED_SITES in "
        "``tests/test_l19_no_redundant_refresh.py``. Offenders:\n  - "
        + "\n  - ".join(f"{rel}:{lineno} in {q} (refresh({r}))" for rel, q, lineno, r in plain)
    )


def test_refresh_sites_match_allowlist() -> None:
    """Every retained ``session.refresh`` site must be in ``ALLOWED_SITES``.

    Removes the file:line shape (which moves with edits) and matches on
    ``(file, qualified-function, refreshed-var, sorted-attr-names)``.
    The allowlist documents the per-site rationale in its comments.
    """
    sites = _collect_refresh_sites()
    observed = frozenset(
        (rel, qualified, refreshed, attrs or ())
        for rel, qualified, _lineno, refreshed, attrs in sites
    )

    unexpected = observed - ALLOWED_SITES
    missing = ALLOWED_SITES - observed

    msgs: list[str] = []
    if unexpected:
        msgs.append(
            "Unexpected ``session.refresh`` site(s) — add to ALLOWED_SITES "
            "after audit:\n  - " + "\n  - ".join(repr(s) for s in sorted(unexpected))
        )
    if missing:
        msgs.append(
            "ALLOWED_SITES references entr(y/ies) that no longer exist in "
            "the codebase — remove from the allowlist:\n  - "
            + "\n  - ".join(repr(s) for s in sorted(missing))
        )
    assert not msgs, "\n\n".join(msgs)
