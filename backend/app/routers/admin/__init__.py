"""Admin panel endpoints — mounted at ``/api/admin``.

Every route in this package is gated behind :func:`deps.require_admin`
(or :func:`deps.require_admin_or_arbiter` for the arbitration subset).
All state-changing endpoints write to ``admin_audit_log`` in the same
transaction as the mutation, so partial failures leave neither a stale
audit row nor an undocumented change.
"""

from . import (
    analytics,
    arbitration,
    audit,
    broadcasts,
    content,
    dashboard,
    deals,
    deposits,
    settings,
    system,
    taxonomy,
    twofa,
    users,
    wallets,
    withdrawals,
)

routers = [
    dashboard.router,
    users.router,
    deals.router,
    arbitration.router,
    content.router,
    wallets.router,
    deposits.router,
    withdrawals.router,
    settings.router,
    taxonomy.router,
    broadcasts.router,
    analytics.router,
    system.router,
    audit.router,
    twofa.router,
]
