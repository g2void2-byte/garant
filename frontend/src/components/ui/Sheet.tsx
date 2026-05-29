import { useEffect, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";
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

  const sheetMarkup = (
    <>
      <div
        data-testid="sheet-overlay"
        onClick={onClose}
        className={cn(
          "fixed inset-0 z-50 bg-black/60 backdrop-blur-md transition-opacity duration-300",
          visible ? "opacity-100" : "opacity-0",
        )}
      />
      <div
        ref={drag.elRef}
        data-testid="sheet"
        data-state={visible ? "open" : "closed"}
        style={tgSheetStyle}
        className={cn(
          "fixed z-50 left-0 right-0 bottom-0 flex flex-col",
          tgViewport == null && "min-h-[50vh] max-h-[min(92dvh,92vh)]",
          "bg-panel border-t border-border rounded-t-3xl",
          "transition-transform duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
          visible ? "translate-y-0" : "translate-y-full",
          className,
        )}
      >
        <div
          onPointerDown={drag.onPointerDown}
          onPointerMove={drag.onPointerMove}
          onPointerUp={drag.onPointerUp}
          className="shrink-0 bg-panel pt-3 px-4 z-10 touch-none cursor-grab active:cursor-grabbing rounded-t-3xl"
        >
          <div className="mx-auto h-1 w-10 rounded-full bg-text-muted/30" />
          {title && <div className="mt-2 text-center font-medium">{title}</div>}
        </div>
        <div
          style={{ touchAction: "pan-y" }}
          className="flex-1 overflow-y-auto overscroll-contain px-4 pt-3 pb-[calc(env(safe-area-inset-bottom,16px)+16px)]"
        >
          {children}
        </div>
      </div>
    </>
  );

  return typeof document !== "undefined"
    ? createPortal(sheetMarkup, document.body)
    : sheetMarkup;
}
