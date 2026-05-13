import { forwardRef, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  hint?: string;
  error?: string;
}

/**
 * Continental `_textarea_h8408_31` / `_textarea_1msv3_103`:
 *   min-height 150px, bg --dark-color (#282828), no border,
 *   border-radius 8px, padding 12px, placeholder #878787.
 */
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, hint, error, className, ...rest },
  ref,
) {
  return (
    <label className="block">
      {label && (
        <div className="mb-1 text-[14px] font-medium text-text">{label}</div>
      )}
      <textarea
        ref={ref}
        rows={4}
        className={cn(
          "w-full p-3 rounded-button bg-panel text-text border-0 min-h-[150px]",
          "placeholder:text-text-muted focus:outline-none resize-y",
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
