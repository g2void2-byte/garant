import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: string;
  error?: string;
}

/**
 * Continental `_input_1lbd6_28` design:
 *   bg #282828 (dark-color), border: none, border-radius: 8px
 *   height 44px (md) / 40px (sm)
 *   color #fff, placeholder #878787, disabled #5f5f60
 *   font-size: 16px, padding: 0 16px
 */
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, className, ...rest },
  ref,
) {
  return (
    <label className="block">
      {label && (
        <div className="mb-1 text-[14px] font-medium text-text">{label}</div>
      )}
      <input
        ref={ref}
        className={cn(
          "h-11 w-full px-4 rounded-button bg-panel text-text border-0",
          "placeholder:text-text-muted focus:outline-none",
          "disabled:text-text-disabled disabled:cursor-not-allowed",
          error && "ring-1 ring-danger",
          className,
        )}
        {...rest}
      />
      {(hint || error) && (
        <div className={cn("mt-1 text-xs", error ? "text-danger" : "text-text-muted")}>
          {error || hint}
        </div>
      )}
    </label>
  );
});
