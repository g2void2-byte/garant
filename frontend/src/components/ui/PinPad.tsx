import { cn } from "@/lib/cn";
import { haptic } from "@/lib/tg";

interface PinPadProps {
  value: string;
  length?: number;
  disabled?: boolean;
  onChange: (next: string) => void;
  onComplete?: (full: string) => void;
}

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "back"] as const;

export function PinPad({ value, length = 4, disabled, onChange, onComplete }: PinPadProps) {
  function press(key: string) {
    if (disabled) return;
    haptic("light");
    if (key === "back") {
      if (value.length > 0) onChange(value.slice(0, -1));
      return;
    }
    if (!/^\d$/.test(key)) return;
    if (value.length >= length) return;
    const next = value + key;
    onChange(next);
    if (next.length === length && onComplete) onComplete(next);
  }

  return (
    <div className="flex flex-col items-center gap-10 select-none">
      <div className="flex items-center gap-5">
        {Array.from({ length }).map((_, i) => (
          <span
            key={i}
            className={cn(
              "block h-3 w-3 rounded-full transition-colors duration-150",
              i < value.length ? "bg-text animate-pop-dot" : "bg-panel-2",
            )}
          />
        ))}
      </div>
      <div className="grid grid-cols-3 gap-1 w-full max-w-xs">
        {KEYS.map((k, i) => {
          if (k === "") return <span key={i} aria-hidden />;
          if (k === "back") {
            return (
              <button
                key={i}
                type="button"
                onClick={() => press("back")}
                disabled={disabled}
                aria-label="Удалить"
                className="h-[60px] w-full rounded-lg bg-transparent text-text text-2xl active:bg-panel-2 disabled:opacity-40"
              >
                ⌫
              </button>
            );
          }
          return (
            <button
              key={i}
              type="button"
              onClick={() => press(k)}
              disabled={disabled}
              className="h-[60px] w-full rounded-lg bg-panel text-text text-2xl font-medium active:bg-panel-2 disabled:opacity-40"
            >
              {k}
            </button>
          );
        })}
      </div>
    </div>
  );
}
