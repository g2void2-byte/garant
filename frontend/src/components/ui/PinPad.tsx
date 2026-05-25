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
    <div className="flex flex-col items-center gap-12 select-none w-full">
      <div className="flex items-center gap-5">
        {Array.from({ length }).map((_, i) => (
          <span
            key={i}
            className={cn(
              "block h-3.5 w-3.5 rounded-full transition-all duration-150",
              i < value.length
                ? "bg-accent scale-100 animate-pop-dot"
                : "bg-white/15 scale-90",
            )}
          />
        ))}
      </div>
      <div className="grid grid-cols-3 gap-y-6 gap-x-10 w-full max-w-[280px]">
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
                className="h-14 w-full grid place-items-center text-text/80 text-2xl font-light active:text-accent active:scale-90 transition-transform disabled:opacity-40"
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
              className="h-14 w-full grid place-items-center text-text text-[32px] font-light leading-none active:text-accent active:scale-90 transition-transform disabled:opacity-40"
            >
              {k}
            </button>
          );
        })}
      </div>
    </div>
  );
}
