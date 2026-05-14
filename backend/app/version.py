"""Single source of truth for the backend version string.

Surfaced by ``/api/admin/system/status`` so the admin "System" page
shows a stable identifier across deploys without having to read it
from a runtime-only attribute.
"""

from __future__ import annotations

BACKEND_VERSION = "2.0.0"
