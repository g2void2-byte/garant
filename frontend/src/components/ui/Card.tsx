import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  interactive?: boolean;
  inset?: boolean;
}

/**
 * Continental cards: bg --dark-color (#282828), border-radius 14px,
 * padding 16px, no border. `inset` swaps to the secondary surface
 * (#383838) for nested sub-cards.
 */
export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { className, interactive, inset, children, ...rest },
  ref,
) {
  const base = cn(
    "bg-panel rounded-card p-4",
    inset && "bg-secondary",
    interactive && "active:scale-[0.99] transition-transform duration-100",
    className,
  );

  return (
    <div ref={ref} className={base} {...rest}>
      {children}
    </div>
  );
});
