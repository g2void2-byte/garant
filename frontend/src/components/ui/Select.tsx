import { ChevronDown, SlidersHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { haptic } from "@/lib/tg";
import { usePresence } from "@/lib/animate";

export interface SelectOption<T extends string> {
  value: T;
  label: string;
}

interface SelectProps<T extends string> {
  value: T;
  options: SelectOption<T>[];
  onChange: (value: T) => void;
  className?: string;
  withIcon?: boolean;
  placeholder?: string;
}

export function Select<T extends string>({
  value,
  options,
  onChange,
  className,
  withIcon = true,
  placeholder,
}: SelectProps<T>) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const current = options.find((o) => o.value === value);
  const { mounted, visible } = usePresence(open, 150);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    if (open) document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  return (
    <div ref={ref} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => {
          haptic("select");
          setOpen((s) => !s);
        }}
        className={cn(
          "flex w-full items-center justify-between gap-2 h-12 px-3 rounded-2xl",
          "bg-panel-2 border border-border text-text hover:border-text-muted/40 transition-colors",
        )}
      >
        <span className="inline-flex items-center gap-2 truncate">
          {withIcon && <SlidersHorizontal className="size-4 text-text-muted" />}
          <span className={cn(!current && "text-text-muted")}>{current?.label ?? placeholder ?? "Все"}</span>
        </span>
        <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
      </button>
      {mounted && (
        <div
          className={cn(
            "absolute left-0 right-0 z-30 mt-1 overflow-hidden rounded-2xl border border-border bg-panel shadow-pop",
            "transition-all duration-150",
            visible ? "opacity-100 translate-y-0" : "opacity-0 -translate-y-1.5",
          )}
        >
          <ul className="max-h-[260px] overflow-y-auto py-1">
            {options.map((opt) => (
              <li key={opt.value}>
                <button
                  type="button"
                  className={cn(
                    "flex w-full items-center justify-between px-3 py-3 text-left text-sm hover:bg-panel-2",
                    opt.value === value && "text-accent",
                  )}
                  onClick={() => {
                    onChange(opt.value);
                    setOpen(false);
                  }}
                >
                  {opt.label}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
