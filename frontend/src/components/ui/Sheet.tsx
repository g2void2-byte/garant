import { useEffect, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { usePresence, useVerticalDrag } from "@/lib/animate";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  className?: string;
}

export function Sheet({ open, onClose, title, children, className }: SheetProps) {
  const { mounted, visible } = usePresence(open, 300);
  const drag = useVerticalDrag(onClose);

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
          "fixed inset-0 z-50 bg-black/70 backdrop-blur-sm transition-opacity duration-300",
          visible ? "opacity-100" : "opacity-0",
        )}
        onClick={onClose}
      />
      <div
        ref={drag.elRef}
        className={cn(
          "fixed z-50 left-0 right-0 bottom-0 flex flex-col",
          "max-h-[88dvh] bg-panel border-t border-border rounded-t-3xl",
          "transition-transform duration-300",
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
          {title && <div className="mt-3 text-lg font-bold">{title}</div>}
        </div>
        <div className="flex-1 overflow-y-auto overscroll-contain px-4 pt-3 pb-[calc(env(safe-area-inset-bottom,16px)+16px)]">
          {children}
        </div>
      </div>
    </>
  );
}
