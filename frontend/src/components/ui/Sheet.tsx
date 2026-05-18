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
          "fixed z-50 left-0 right-0 bottom-0 max-h-[85dvh] overflow-y-auto overscroll-contain",
          "bg-panel border-t border-border rounded-t-3xl px-4 pb-4 safe-bottom",
          "transition-transform duration-300",
          visible ? "translate-y-0" : "translate-y-full",
          className,
        )}
      >
        <div
          onPointerDown={drag.onPointerDown}
          onPointerMove={drag.onPointerMove}
          onPointerUp={drag.onPointerUp}
          className="sticky top-0 bg-panel pt-3 -mx-4 px-4 z-10 touch-none cursor-grab active:cursor-grabbing"
        >
          <div className="mx-auto h-1 w-10 rounded-full bg-text-muted/30" />
          {title && <div className="mt-3 text-lg font-bold">{title}</div>}
        </div>
        <div className="pt-3">{children}</div>
      </div>
    </>
  );
}
