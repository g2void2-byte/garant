import { useEffect, useRef, useState, useCallback } from "react";
import { cn } from "@/lib/cn";
import { haptic } from "@/lib/tg";

export interface ToggleOption<T extends string> {
  value: T;
  label: string;
  icon?: React.ReactNode;
  count?: number;
}

interface ToggleTabsProps<T extends string> {
  value: T;
  options: ToggleOption<T>[];
  onChange: (value: T) => void;
  className?: string;
}

export function ToggleTabs<T extends string>({
  value,
  options,
  onChange,
  className,
}: ToggleTabsProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [pill, setPill] = useState({ left: 0, width: 0 });

  const updatePill = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const idx = options.findIndex((o) => o.value === value);
    const btn = container.children[idx + 1] as HTMLElement | undefined;
    if (btn) {
      setPill({ left: btn.offsetLeft, width: btn.offsetWidth });
    }
  }, [value, options]);

  useEffect(() => {
    updatePill();
    window.addEventListener("resize", updatePill);
    return () => window.removeEventListener("resize", updatePill);
  }, [updatePill]);

  return (
    <div ref={containerRef} className={cn("relative inline-flex w-full rounded-2xl bg-panel-2 p-1 gap-1", className)}>
      <span
        className="absolute rounded-xl bg-accent transition-all duration-200 ease-out"
        style={{ left: pill.left, width: pill.width, top: 4, bottom: 4 }}
      />
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => {
              if (!active) {
                haptic("select");
                onChange(opt.value);
              }
            }}
            className={cn(
              "relative flex-1 inline-flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl",
              "font-semibold text-sm transition-colors duration-200",
              active ? "text-accent-fg" : "text-text-muted hover:text-text",
            )}
          >
            <span className="relative z-10 inline-flex items-center gap-2">
              {opt.icon}
              <span>{opt.label}</span>
              {opt.count != null && (
                <span
                  className={cn(
                    "ml-1 inline-flex items-center justify-center min-w-[20px] h-5 px-1 rounded-full text-[11px] font-bold",
                    active ? "bg-accent-fg/10 text-accent-fg" : "bg-panel text-text-muted",
                  )}
                >
                  {opt.count}
                </span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}
