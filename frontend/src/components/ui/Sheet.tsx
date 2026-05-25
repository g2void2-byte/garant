import { useEffect, type CSSProperties, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { usePresence, useVerticalDrag } from "@/lib/animate";
import { useTelegramViewport } from "@/lib/tg";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  className?: string;
}

export function Sheet({
  open,
  onClose,
  title,
  children,
  className,
}: SheetProps) {
  const { mounted, visible } = usePresence(open, 300);
  const drag = useVerticalDrag(onClose);
  // V13.2 — read the real Telegram WebApp viewport (px) so the
  // sheet never overflows the iframe on Telegram Desktop where
  // ``100dvh`` does not match the Mini App container until
  // ``WebApp.expand()`` AND ``viewportChanged`` fires. Outside of
  // Telegram (dev browser, jsdom) the hook returns ``null`` and we
  // fall back to a CSS ``min(92dvh, 92vh)`` ceiling that behaves
  // correctly in a normal browser tab. Fixes the "empty grey sheet
  // floats at the top of the screen" bug seen in items 2/5/6.
  const tgViewport = useTelegramViewport();
  const tgSheetStyle: CSSProperties | undefined =
    tgViewport != null
      ? {
          maxHeight: Math.round(tgViewport * 0.92),
          minHeight: Math.round(tgViewport * 0.5),
        }
      : undefined;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!mounted) return null;

  return (
    <>
      <div
        className={cn(
          // V13 — heavier blur ``backdrop-blur-md`` + a slightly
          // lighter overlay ``bg-black/60`` reads better behind a
          // sheet that often dominates the screen on iOS Safari /
          // Telegram WebView.
          "fixed inset-0 z-50 bg-black/60 backdrop-blur-md",
          "transition-opacity duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
          visible ? "opacity-100" : "opacity-0",
        )}
        onClick={onClose}
      />
      <div
        ref={drag.elRef}
        data-testid="sheet"
        data-state={visible ? "open" : "closed"}
        style={tgSheetStyle}
        className={cn(
          "fixed z-50 left-0 right-0 bottom-0 flex flex-col",
          // V13.2 — in Telegram we drive height from ``tgSheetStyle``
          // (computed from ``WebApp.viewportStableHeight``). Outside
          // of Telegram (dev browser, screenshot tests) we keep the
          // CSS fallback so the sheet still renders sensibly in
          // a plain browser tab. ``min(92dvh,92vh)`` defends against
          // the iOS Safari ``dvh`` / ``vh`` divergence; without it
          // the sheet could exceed the visible area on a 100% zoom
          // page when ``dvh`` reports a value larger than the
          // physical viewport.
          tgViewport == null && "min-h-[50vh] max-h-[min(92dvh,92vh)]",
          "bg-panel border-t border-border rounded-t-3xl",
          // V13 — spring-like easing matches the Continental
          // Telegram aesthetic better than the default ease-in-out.
          "transition-transform duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
          visible ? "translate-y-0" : "translate-y-full",
          className,
        )}
      >
        <div
          onPointerDown={drag.onPointerDown}
          onPointerMove={drag.onPointerMove}
          onPointerUp={drag.onPointerUp}
          // V13.1 — ``touch-none`` so the dismissal drag doesn't
          // conflict with vertical scroll inside the sheet body; the
          // handle is the *only* place that owns vertical pointer
          // gestures. Body scrolling is opted-in explicitly below.
          className="shrink-0 bg-panel pt-3 px-4 z-10 touch-none cursor-grab active:cursor-grabbing rounded-t-3xl"
        >
          <div className="mx-auto h-1 w-10 rounded-full bg-text-muted/30" />
          {title && <div className="mt-3 text-lg font-bold">{title}</div>}
        </div>
        <div
          // V13.1 — ``touch-action: pan-y`` lets Telegram’s iOS
          // WebView surface the inner overflow scroll even after
          // ``AdminMenu`` set ``body.style.overflow = "hidden"``.
          // Without it, long composer forms (broadcasts, filter
          // sheet on TMA) appear stuck on first paint because the
          // top of the form is off-screen and the body refuses to
          // scroll. Children opt into a sticky-footer row inside
          // ``children`` (see ``AdminBroadcastsPage`` Composer) so
          // the primary CTA stays visible regardless of form length.
          style={{ touchAction: "pan-y" }}
          className="flex-1 overflow-y-auto overscroll-contain px-4 pt-3 pb-[calc(env(safe-area-inset-bottom,16px)+16px)]"
        >
          {children}
        </div>
      </div>
    </>
  );
}
