"""Media upload + retrieval.

PR-E introduces a generic media store used by avatar / banner uploads and,
in the future, deal-chat attachments. Files are written to
``settings.media_root`` on local disk and served through the
``settings.media_base_url`` mount point on the same backend host.

Allowed kinds are configured via ``settings.media_allowed_kinds``.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..config import settings
from ..deps import CurrentUser, SessionDep
from ..models import Media
from ..rate_limit import RLMediaUpload
from ..schemas import MediaOut
from ..time_utils import utcnow

router = APIRouter(prefix="/api/media", tags=["media"])


# Canonical (content-type → on-disk extension) mapping. The saved file
# always uses the extension this mapping returns — *never* the
# user-supplied filename — so a client can't trick StaticFiles into
# serving the upload as ``text/html``, ``image/svg+xml``, ``text/xml``
# etc. (anything that browsers will execute as active content).
_ALLOWED_IMAGE_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _allowed_kinds() -> set[str]:
    return {k.strip() for k in settings.media_allowed_kinds.split(",") if k.strip()}


def _ensure_root() -> Path:
    root = Path(settings.media_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _media_out(m: Media) -> MediaOut:
    return MediaOut(
        id=m.id,
        kind=m.kind,
        url=m.url,
        name=m.name,
        size=m.size,
        content_type=m.content_type,
        created_at=m.created_at,
    )


def _safe_extension(content_type: str) -> str | None:
    """Return the canonical disk extension for a *validated* content-type.

    Filenames are not consulted — they're attacker-controlled and were
    previously echoed onto disk, which let ``foo.html`` end up served as
    ``text/html`` from the backend origin.
    """
    return _ALLOWED_IMAGE_TYPES.get(content_type)


@router.post("/upload", response_model=MediaOut, status_code=201)
async def upload_media(
    user: CurrentUser,
    session: SessionDep,
    _rl: RLMediaUpload,
    kind: str = Form(...),
    file: UploadFile = File(...),
):
    allowed = _allowed_kinds()
    if kind not in allowed:
        raise HTTPException(400, f"Недопустимый kind: {kind}")

    content_type = file.content_type or "application/octet-stream"
    # Image MIME allowlist is now enforced for *every* kind. The previous
    # ``kind in {avatar, banner}`` carve-out left ``deal`` accepting any
    # content-type, and combined with the old filename-derived extension
    # let a client smuggle an HTML file onto the same backend origin.
    ext = _safe_extension(content_type)
    if ext is None:
        raise HTTPException(415, "Допустимы только PNG / JPEG / WebP / GIF")

    data = await file.read()
    if not data:
        raise HTTPException(400, "Файл пустой")
    if len(data) > settings.media_max_bytes:
        raise HTTPException(413, f"Файл слишком большой (>{settings.media_max_bytes // 1024} КБ)")

    root = _ensure_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)

    name = f"{user.id}-{utcnow().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(6)}{ext}"
    path = folder / name
    path.write_bytes(data)

    base = settings.media_base_url.rstrip("/")
    url = f"{base}/{kind}/{name}"

    media = Media(
        owner_id=user.id,
        kind=kind,
        url=url,
        name=file.filename or name,
        size=len(data),
        content_type=content_type,
    )
    session.add(media)
    await session.commit()
    await session.refresh(media)
    return _media_out(media)
