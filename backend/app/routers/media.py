"""Media upload + retrieval.

PR-E introduces a generic media store used by avatar / banner uploads and,
in the future, deal-chat attachments. Files are written to
``settings.media_root`` on local disk and served through the
``settings.media_base_url`` mount point on the same backend host.

Allowed kinds are configured via ``settings.media_allowed_kinds``.
"""

from __future__ import annotations

import asyncio
import io
import secrets
from pathlib import Path
from typing import Any, Final

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from ..config import settings
from ..deps import CurrentUser, SessionDep
from ..media_signing import signed_media_url
from ..models import Media
from ..rate_limit import RLMediaUpload
from ..schemas import MediaOut
from ..time_utils import utcnow

router = APIRouter(prefix="/api/media", tags=["media"])


# L-6 — stream uploads in 64 KiB chunks instead of buffering the full
# body up-front. Small enough that an oversized payload is aborted
# within a few iterations (bounded peak memory), large enough that the
# per-chunk syscall / await overhead stays amortised for a 5 MiB image.
_UPLOAD_CHUNK_BYTES: Final[int] = 64 * 1024

# L-5 — hard cap on decoded pixel count to defuse decompression bombs.
# Pillow's stock ``Image.MAX_IMAGE_PIXELS`` only ``warnings.warn()``s,
# which means a 10 KB PNG that decompresses to 200M pixels would still
# allocate the full RGBA buffer and OOM the worker.  50M pixels (~190
# MiB RGBA on the decode side) is generous for legitimate avatars and
# deal-chat screenshots but well under the worker's RSS budget.
_MAX_IMAGE_PIXELS: Final[int] = 50_000_000

# L-5 — Pillow ``save()`` format identifier keyed by content-type.
# Kept aligned with ``_ALLOWED_IMAGE_TYPES`` below; adding a new type
# requires touching both maps so a missed entry trips a ``KeyError``
# at decode time rather than a silent pass-through.
_PILLOW_FORMATS: dict[str, str] = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/webp": "WEBP",
    "image/gif": "GIF",
}


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


# Per-content-type magic-byte signatures. Validated against the head
# of the upload payload BEFORE write so a client cannot smuggle e.g.
# an HTML or SVG file under ``Content-Type: image/png`` — even though
# the on-disk extension is locked, the static-file mount sets
# ``Content-Type`` from the extension only, so a browser would still
# render an HTML payload as text/html via content-sniffing on the
# fetch side without this check.
#
# Sources: each format's official spec. WebP uses a RIFF container,
# so we match both the leading ``RIFF`` and the inner ``WEBP``
# marker at offset 8. JPEG variants all start with ``FF D8 FF``.
def _matches_magic(content_type: str, data: bytes) -> bool:
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/gif":
        return data.startswith(b"GIF87a") or data.startswith(b"GIF89a")
    if content_type == "image/webp":
        return len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def _allowed_kinds() -> set[str]:
    return {k.strip() for k in settings.media_allowed_kinds.split(",") if k.strip()}


async def _ensure_root() -> Path:
    # M-6: hop blocking filesystem operations onto the worker thread
    # pool so the event loop stays responsive under concurrent
    # uploads. ``mkdir(parents=True, exist_ok=True)`` is idempotent
    # so retries from racing callers are safe.
    root = Path(settings.media_root).expanduser().resolve()
    await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
    return root


def _media_out(m: Media) -> MediaOut:
    # Audit v3 L-14 — buckets listed in ``settings.media_signed_kinds``
    # (deal-chat attachments by default) get an HMAC-signed URL with
    # a short ``?exp=`` window so a leaked link goes stale instead of
    # being usable forever.  Public buckets (avatar / banner /
    # service) keep the unsigned ``StaticFiles`` URL — they're already
    # exposed on user profiles.
    return MediaOut(
        id=m.id,
        kind=m.kind,
        url=signed_media_url(url=m.url, kind=m.kind),
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


# ``Media.name`` mirrors what the client claimed the file was called,
# purely as a UX hint for the gallery / admin viewer.  The raw value is
# attacker-controlled (``multipart/form-data`` ``Content-Disposition``)
# and was previously written into ``media.name`` unchanged.  That string
# round-trips back to the frontend as ``MediaOut.name`` and (depending
# on logging) can surface in admin views, so we strip the obvious
# foot-guns before it ever lands in the DB:
#
# * NUL / CR / LF / other ASCII control bytes — log-injection / CRLF
#   header-smuggling if the value is ever echoed into a header or a
#   logger that doesn't escape its message.
# * Path separators ``/`` and ``\\`` and the ``..`` traversal token —
#   not actually used in the filesystem write (the on-disk name is
#   server-generated), but a defence-in-depth strip keeps anything
#   downstream from accidentally treating the stored ``name`` as a
#   path component.
#
# The on-disk extension and URL are always the server-generated
# ``name`` variable — this sanitisation only affects the display
# string stored on ``media.name``.
_FILENAME_BAD_CHARS = "".join(chr(c) for c in range(0x20)) + "\x7f"
_FILENAME_BAD_TRANS = str.maketrans({c: "_" for c in _FILENAME_BAD_CHARS})


def _sanitise_display_name(raw: str | None, *, fallback: str) -> str:
    """Sanitise an attacker-controlled filename for the ``media.name`` column.

    Returns ``fallback`` when ``raw`` is empty / pure-whitespace after
    cleaning so the column always contains a non-empty value (mirrors the
    existing ``file.filename or name`` fallback).  The result is capped at
    255 bytes so it always fits the ``String(256)`` column even after the
    SQLAlchemy / asyncpg encoding round-trip.
    """
    if not raw:
        return fallback
    s = raw.translate(_FILENAME_BAD_TRANS).replace("\\", "_").replace("/", "_")
    # Collapse traversal tokens (``..``) and surrounding whitespace; the
    # on-disk filename never sees this string, but downstream consumers
    # might treat it as a path component, so strip the obvious markers.
    s = s.replace("..", "_").strip()
    if not s:
        return fallback
    # 255 chars stays comfortably under the ``String(256)`` cap even for
    # multibyte UTF-8 inputs (Postgres counts characters, not bytes, for
    # ``varchar`` length).
    return s[:255]


async def _stream_capped(file: UploadFile, cap: int) -> bytes:
    """Drain the upload in fixed-size chunks, aborting the moment the
    accumulated size exceeds ``cap``.

    L-6 motivation: a bare ``await file.read()`` returns *all* of the
    spooled body before we ever look at it, so a client posting a
    1 GiB blob would spend the full spool before the size check fires.
    Reading in ``_UPLOAD_CHUNK_BYTES``-sized slices and tripping the
    413 as soon as the running total crosses the cap keeps peak
    memory bounded by the cap itself rather than by the body length
    the client happens to advertise.
    """
    buf = bytearray()
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        # Audit 5.1 — pre-check the would-be size before extending so
        # we never over-allocate by up to ``_UPLOAD_CHUNK_BYTES`` past
        # the cap on the final chunk.  Keeps peak memory bounded by
        # ``cap`` exactly instead of ``cap + chunk_size``.
        if len(buf) + len(chunk) > cap:
            raise HTTPException(
                413,
                f"Файл слишком большой (>{cap // 1024} КБ)",
            )
        buf.extend(chunk)
    return bytes(buf)


def _reencode_image(data: bytes, content_type: str) -> bytes:
    """Decode + re-encode the image through Pillow as a defensive sieve.

    L-5 threat model: the magic-byte gate only validates the first
    8–12 bytes; everything that follows is opaque to the upload
    handler.  A crafted payload that satisfies the header check can
    still smuggle malformed chunks, oversized metadata, or
    intentionally-huge dimensions — vectors that have historically
    surfaced as libpng / libwebp / ImageMagick RCEs and as
    decompression-bomb DoS.

    Re-encoding strips every byte the decoder didn't consume (EXIF,
    ICC profiles, comment chunks, trailing garbage) and fails closed
    on payloads that don't fully parse, so what lands on disk is
    always a fresh container holding only the decoded pixel buffer.
    The pixel-count cap (`_MAX_IMAGE_PIXELS`) is enforced *before*
    ``load()`` so a bomb header never allocates the underlying
    buffer.

    Audit §4.15 — animated GIF / WebP payloads are now rejected
    outright with HTTP 415.  Pre-fix the re-encode pass silently
    flattened them to the first frame, which (a) violated user
    intent without surfacing an error and (b) kept the multi-frame
    Pillow decode surface — historically the source of most
    image-library CVE traffic — reachable from anonymous upload.
    The avatar / deal-attachment use case does not need animation,
    so detecting ``is_animated`` / ``n_frames > 1`` and refusing
    the upload is both stricter on the parser surface and honest
    about the displayed result.
    """
    fmt = _PILLOW_FORMATS[content_type]
    out = io.BytesIO()
    try:
        with Image.open(io.BytesIO(data)) as img:
            w, h = img.size
            if w * h > _MAX_IMAGE_PIXELS:
                raise HTTPException(
                    415,
                    "Изображение слишком большое (превышен лимит пикселей)",
                )
            # Audit §4.15 — fail closed on multi-frame containers.
            # ``Image.is_animated`` is the canonical Pillow flag; some
            # plugins expose ``n_frames`` instead, and the boolean
            # short-circuits when only one is set.  Both are read
            # before ``load()`` so we never decode beyond the first
            # frame for the rejected case.
            if getattr(img, "is_animated", False) or getattr(img, "n_frames", 1) > 1:
                raise HTTPException(
                    415,
                    "Анимированные изображения не поддерживаются",
                )
            save_kwargs: dict[str, Any] = {}
            if fmt == "JPEG":
                # JPEG has no alpha channel; flatten transparency onto
                # white so palette / RGBA inputs survive the round-trip
                # instead of raising ``OSError: cannot write mode RGBA``.
                if img.mode in ("RGBA", "LA", "P"):
                    flat = Image.new("RGB", img.size, "white")
                    alpha = img.convert("RGBA")
                    flat.paste(alpha, mask=alpha.split()[-1])
                    img = flat
                else:
                    img = img.convert("RGB")
                save_kwargs["quality"] = 90
                save_kwargs["optimize"] = False
            else:
                # Force a full decode here so an early-truncation
                # ``OSError`` is raised inside this ``try`` block
                # rather than propagating from inside ``save()``.
                img.load()
            img.save(out, format=fmt, **save_kwargs)
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise HTTPException(415, "Не удалось распознать изображение") from None
    return out.getvalue()


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

    data = await _stream_capped(file, settings.media_max_bytes)
    if not data:
        raise HTTPException(400, "Файл пустой")

    # Magic-byte check: the declared ``Content-Type`` is attacker-
    # controlled, so cross-check it against the actual file header
    # before persisting. Without this gate a client could POST e.g.
    # an HTML payload under ``Content-Type: image/png``; the
    # extension is locked to ``.png``, but in some deployments the
    # static-file server / CDN sniffs the body or serves with
    # ``X-Content-Type-Options`` missing, and a browser would happily
    # render the HTML as active content from the backend origin.
    #
    # The magic-byte gate is cheap (8 bytes) and runs before Pillow
    # so an obvious HTML/script payload short-circuits without
    # spinning up the decoder.  Pillow's own format detection is
    # tolerant of trailing garbage and would happily decode the first
    # IDAT chunk of a smuggled payload, so we keep both checks.
    if not _matches_magic(content_type, data):
        raise HTTPException(415, "Файл не соответствует заявленному типу")

    # L-5 — defensive Pillow re-encode.  See ``_reencode_image`` for
    # the threat model; running it through ``asyncio.to_thread``
    # because Pillow is pure CPU work and would otherwise stall the
    # event loop on a 5 MiB image.
    sanitised = await asyncio.to_thread(_reencode_image, data, content_type)

    root = await _ensure_root()
    folder = root / kind
    # M-6: same rationale as ``_ensure_root`` — keep the loop free of
    # blocking ``mkdir`` / ``write_bytes`` syscalls so a slow disk
    # doesn't stall every other request on the worker.
    await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)

    name = f"{user.id}-{utcnow().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(6)}{ext}"
    path = folder / name
    await asyncio.to_thread(path.write_bytes, sanitised)

    base = settings.media_base_url.rstrip("/")
    url = f"{base}/{kind}/{name}"

    media = Media(
        owner_id=user.id,
        kind=kind,
        url=url,
        # ``file.filename`` is attacker-controlled (set by the
        # multipart ``Content-Disposition`` header), so strip control
        # bytes / path separators before it lands in the DB.  The
        # server-generated ``name`` is the safe fallback when the
        # client supplied an empty / unusable string.
        name=_sanitise_display_name(file.filename, fallback=name),
        size=len(sanitised),
        content_type=content_type,
    )
    session.add(media)
    await session.commit()
    return _media_out(media)
