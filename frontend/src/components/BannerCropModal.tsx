import { useCallback, useEffect, useState } from "react";
import Cropper, { type Area } from "react-easy-crop";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { haptic } from "@/lib/tg";

/**
 * Bug-7 — banner-crop editor. Mounted by ``SettingsPage`` between
 * the file picker (``<input type=file>``) and ``useUploadMedia``.
 *
 * Flow:
 *   1. User taps "Загрузить баннер".
 *   2. ``onChange`` reads the picked ``File`` and opens this modal.
 *   3. User drags / zooms inside a fixed 16:10 frame.
 *   4. "Применить" crops the source onto a canvas, exports a JPEG
 *      ``Blob``, wraps it in a ``File`` and resolves the supplied
 *      ``onApply`` callback so the caller can run its existing
 *      ``useUploadMedia`` mutation against the cropped file.
 *
 * The component does **not** speak to the backend itself — the
 * caller decides the upload mutation, error toast, and
 * post-success state update. That keeps the modal reusable across
 * any future "crop before upload" surfaces (service photos, etc.)
 * without re-implementing the upload chain.
 */
interface BannerCropModalProps {
  open: boolean;
  file: File | null;
  /** Aspect ratio (width / height). Defaults to 16:10 to match ``ProfileHeader``'s ``h-64`` banner. */
  aspect?: number;
  /** Output JPEG quality (0–1). Defaults to ``0.92``. */
  quality?: number;
  /** Maximum encoded edge length (px). Defaults to ``1600`` so we don't ship 4 MP off a modern phone camera. */
  maxEdgePx?: number;
  onCancel: () => void;
  onApply: (cropped: File) => Promise<void> | void;
}

const ZOOM_INPUT_RE = /^(?:\d+(?:\.\d+)?|\.\d+)$/;

export function parseBannerZoomInput(raw: string, fallback: number): number {
  const value = raw.trim();
  if (!ZOOM_INPUT_RE.test(value)) return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(3, Math.max(1, parsed));
}

export function BannerCropModal({
  open,
  file,
  aspect = 16 / 10,
  quality = 0.92,
  maxEdgePx = 1600,
  onCancel,
  onApply,
}: BannerCropModalProps) {
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [pixelCrop, setPixelCrop] = useState<Area | null>(null);
  const [busy, setBusy] = useState(false);

  // Generate / revoke the object URL for the picked file. We can't
  // hand ``react-easy-crop`` a ``File`` directly — it needs an
  // ``<img src>``-compatible URL. Cleanup is essential because
  // browsers don't GC blob URLs automatically.
  useEffect(() => {
    if (!file) {
      setImageSrc(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setImageSrc(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  // Reset internal crop state every time a new file is loaded so
  // the user doesn't inherit the previous picture's zoom level.
  useEffect(() => {
    if (file) {
      setCrop({ x: 0, y: 0 });
      setZoom(1);
      setPixelCrop(null);
    }
  }, [file]);

  const onCropComplete = useCallback(
    (_area: Area, areaPixels: Area) => setPixelCrop(areaPixels),
    [],
  );

  async function handleApply() {
    if (!file || !imageSrc || !pixelCrop) {
      haptic("error");
      return;
    }
    setBusy(true);
    try {
      const blob = await cropToBlob(imageSrc, pixelCrop, {
        type: file.type === "image/png" ? "image/png" : "image/jpeg",
        quality,
        maxEdgePx,
      });
      const base = file.name.replace(/\.[^.]+$/, "") || "banner";
      const ext = blob.type === "image/png" ? "png" : "jpg";
      const cropped = new File([blob], `${base}-cropped.${ext}`, {
        type: blob.type,
        lastModified: Date.now(),
      });
      await onApply(cropped);
    } catch (err) {
      haptic("error");
      // Surface failure via the caller's existing toast handling —
      // re-throwing would unmount the sheet before the user could
      // retry. Swallow + log; ``onApply`` is also responsible for
      // its own error UX.
      console.error("BannerCropModal: cropping failed", err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open={open} onClose={busy ? () => {} : onCancel} title="Кадрировать баннер">
      {imageSrc && (
        <div className="space-y-3 pb-2">
          <div className="relative w-full overflow-hidden rounded-card bg-black/40 h-[260px]">
            <Cropper
              image={imageSrc}
              crop={crop}
              zoom={zoom}
              aspect={aspect}
              minZoom={1}
              maxZoom={3}
              cropShape="rect"
              showGrid
              onCropChange={setCrop}
              onZoomChange={setZoom}
              onCropComplete={onCropComplete}
            />
          </div>
          <div className="flex items-center gap-3 px-1">
            <span className="text-xs text-text-muted shrink-0">Масштаб</span>
            <input
              type="range"
              min={1}
              max={3}
              step={0.01}
              value={zoom}
              onChange={(e) => setZoom((current) => parseBannerZoomInput(e.target.value, current))}
              aria-label="Масштаб"
              className="flex-1"
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Button variant="secondary" onClick={onCancel} disabled={busy}>
              Отмена
            </Button>
            <Button onClick={handleApply} disabled={busy || !pixelCrop}>
              {busy ? "Готовлю..." : "Применить"}
            </Button>
          </div>
        </div>
      )}
    </Sheet>
  );
}

interface CropOptions {
  type: "image/jpeg" | "image/png";
  quality: number;
  maxEdgePx: number;
}

/**
 * Crop ``src`` to ``area`` and encode as a Blob. The output is
 * downscaled so the longest edge is at most ``maxEdgePx`` so a
 * modern phone camera (12 MP raw) doesn't ship 4 MB of JPEG over a
 * mobile network — Telegram WebView is happy with ~1600px banners.
 */
async function cropToBlob(
  src: string,
  area: Area,
  opts: CropOptions,
): Promise<Blob> {
  const image = await loadImage(src);
  const scale = Math.min(
    1,
    opts.maxEdgePx / Math.max(area.width, area.height),
  );
  const targetW = Math.max(1, Math.round(area.width * scale));
  const targetH = Math.max(1, Math.round(area.height * scale));
  const canvas = document.createElement("canvas");
  canvas.width = targetW;
  canvas.height = targetH;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    throw new Error("2D canvas unavailable");
  }
  ctx.drawImage(
    image,
    area.x,
    area.y,
    area.width,
    area.height,
    0,
    0,
    targetW,
    targetH,
  );
  return await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new Error("canvas.toBlob returned null"));
      },
      opts.type,
      opts.quality,
    );
  });
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    // The source is an object URL we own, so CORS isn't a concern.
    img.src = src;
  });
}
