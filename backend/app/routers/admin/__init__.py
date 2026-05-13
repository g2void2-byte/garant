"""Admin panel endpoints — mounted at ``/api/admin``.

Every route in this package is gated behind :func:`deps.require_admin`
(or :func:`deps.require_admin_or_arbiter` for the arbitration subset).
All state-changing endpoints write to ``admin_audit_log`` in the same
transaction as the mutation, so partial failures leave neither a stale
audit row nor an undocumented change.
"""

from . import arbitration, content, dashboard, deals, users

routers = [
    dashboard.router,
    users.router,
    deals.router,
    arbitration.router,
    content.router,
]
