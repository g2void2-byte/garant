"""N-1: centralised router registry.

Import ``all_routers`` in ``main.py`` instead of manually listing each
module there. This keeps ``main.py`` focused on app-level wiring.
"""

from __future__ import annotations

from . import (
    account,
    arbitration,
    categories,
    csp_report,
    deal_messages,
    deals,
    me,
    media,
    notifications,
    payments,
    pin,
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
    media.router,
    ws.router,
    csp_report.router,
    services.admin_router,
    *admin_routers,
]
