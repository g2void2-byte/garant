"""N-1: centralised router registry.

Import ``all_routers`` in ``main.py`` instead of manually listing each
module there. This keeps ``main.py`` focused on app-level wiring.
"""

from __future__ import annotations

from . import (
    account,
    arbitration,
    categories,
    client_errors,
    csp_report,
    deal_messages,
    deals,
    forums,
    me,
    media,
    media_serve,
    notifications,
    payments,
    pin,
    public_stats,
    reviews,
    services,
    support,
    users,
    wallet,
    ws,
)
from .admin import routers as admin_routers

all_routers = [
    me.router,
    pin.router,
    account.router,
    categories.router,
    services.router,
    users.router,
    deals.router,
    deal_messages.router,
    reviews.router,
    notifications.router,
    payments.router,
    wallet.router,
    support.router,
    arbitration.router,
    forums.router,
    media.router,
    # Audit v3 L-14 — auth-gated serve route for deal-chat
    # attachments. Must come *before* the ``StaticFiles`` mount in
    # ``main.py`` (Starlette matches routes in insertion order) so
    # the signed-URL handler wins over the catch-all static mount
    # for the ``/media/deal/...`` prefix. The router itself just
    # serves files; uploads still go through ``media.router``.
    media_serve.router,
    ws.router,
    csp_report.router,
    client_errors.router,
    services.admin_router,
    public_stats.router,
    *admin_routers,
]
