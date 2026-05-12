import { motion } from "framer-motion";
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
  layoutId?: string;
}

export function ToggleTabs<T extends string>({
  value,
  options,
  onChange,
  className,
  layoutId = "toggle-pill",
}: ToggleTabsProps<T>) {
  return (
    <div className={cn("relative inline-flex w-full rounded-2xl bg-panel-2 p-1 gap-1", className)}>
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
            {active && (
              <motion.span
                layoutId={layoutId}
                className="absolute inset-0 rounded-xl bg-accent"
                transition={{ type: "spring", stiffness: 500, damping: 32 }}
              />
            )}
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
