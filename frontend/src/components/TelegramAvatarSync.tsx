import { useEffect, useRef } from "react";
import { useMe, useUpdateMe } from "@/api/hooks";
import { getTelegramUser } from "@/lib/tg";

/**
 * V12-UI — On TMA boot, if the current Telegram user has a ``photo_url``
 * exposed via ``initDataUnsafe`` but the backend ``User`` row does not
 * have one stored, transparently push the URL up via ``PATCH /api/me``.
 *
 * Telegram only surfaces ``photo_url`` for the user *currently viewing*
 * the Mini App — not for other users — so this lets the avatar circle
 * render their actual TG photo on every device (and other people see
 * it too once the row is updated). The patch fires at most once per
 * mount and is silently dropped on failure (Settings still works as a
 * manual fallback).
 */
export function TelegramAvatarSync() {
  const { data: me } = useMe();
  const updateMe = useUpdateMe();
  const synced = useRef(false);

  useEffect(() => {
    if (synced.current) return;
    if (!me) return;
    const tg = getTelegramUser();
    if (!tg?.photo_url) return;
    if (me.photo_url && me.photo_url === tg.photo_url) return;
    synced.current = true;
    updateMe.mutate({ photo_url: tg.photo_url });
    // Intentionally not awaiting — best-effort sync.
  }, [me, updateMe]);

  return null;
}
