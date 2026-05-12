import { forwardRef, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  hint?: string;
  error?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, hint, error, className, ...rest },
  ref,
) {
  return (
    <label className="block">
      {label && <div className="mb-1.5 text-sm font-medium text-text-muted">{label}</div>}
      <textarea
        ref={ref}
        rows={4}
        className={cn(
          "w-full p-3 rounded-2xl bg-panel-2 border border-border text-text",
          "placeholder:text-text-muted focus:outline-none focus:border-accent transition-colors resize-none",
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
