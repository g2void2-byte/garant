from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.config import settings
from backend.app.routers.media import upload_media
from tests.helpers import tiny_image_bytes


class _FailingSession:
    def add(self, _obj: object) -> None:
        return None

    async def commit(self) -> None:
        raise RuntimeError("simulated db commit failure")


class _FakeUploadFile:
    filename = "avatar.png"
    content_type = "image/png"

    def __init__(self, data: bytes) -> None:
        self._buf = io.BytesIO(data)

    async def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)


@pytest.mark.asyncio
async def test_upload_media_removes_disk_file_when_db_commit_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "media_root", str(tmp_path))

    with pytest.raises(RuntimeError, match="simulated db commit failure"):
        await upload_media(
            user=SimpleNamespace(id=123),
            session=_FailingSession(),
            _rl=None,
            kind="avatar",
            file=_FakeUploadFile(tiny_image_bytes("PNG")),
        )

    assert not [p for p in Path(tmp_path).rglob("*") if p.is_file()]
