import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: string;
  error?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, className, ...rest },
  ref,
) {
  return (
    <label className="block">
      {label && <div className="mb-1.5 text-sm font-medium text-text-muted">{label}</div>}
      <input
        ref={ref}
        className={cn(
          "h-12 w-full px-3 rounded-2xl bg-panel-2 border border-border text-text",
          "placeholder:text-text-muted focus:outline-none focus:border-accent transition-colors",
          error && "border-danger",
          className,
        )}
        {...rest}
      />
      {(hint || error) && (
        <div className={cn("mt-1 text-xs", error ? "text-danger" : "text-text-muted")}>{error || hint}</div>
      )}
    </label>
  );
});
