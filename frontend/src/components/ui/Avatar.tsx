import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";

interface AvatarProps {
  name?: string;
  src?: string | null;
  size?: number;
  className?: string;
}

export function Avatar({ name = "?", src, size = 48, className }: AvatarProps) {
  const letter = name.replace(/^@/, "").trim().charAt(0).toUpperCase() || "?";
  const [broken, setBroken] = useState(false);

  // Reset the broken flag whenever the ``src`` changes so a successful
  // re-upload (or a fresh Telegram CDN URL after re-mount) gets another
  // chance to load instead of staying stuck on the letter fallback.
  useEffect(() => {
    setBroken(false);
  }, [src]);

  const showImage = src && !broken;

  return (
    <div
      style={{ width: size, height: size }}
      className={cn(
        "relative shrink-0 rounded-full overflow-hidden bg-panel-2 border border-border",
        "flex items-center justify-center text-text-muted font-bold",
        className,
      )}
    >
      {showImage ? (
        <img
          src={src}
          alt={name}
          className="w-full h-full object-cover"
          loading="lazy"
          decoding="async"
          // Pre-empts the alt-text bleed-through when Telegram's CDN
          // 403s an expired URL: ``onError`` swaps the broken ``<img>``
          // for the letter ``<span>`` below before the user agent paints
          // the alt-text in the avatar circle.
          referrerPolicy="no-referrer"
          onError={() => setBroken(true)}
        />
      ) : (
        <span style={{ fontSize: size * 0.4 }}>{letter}</span>
      )}
    </div>
  );
}
