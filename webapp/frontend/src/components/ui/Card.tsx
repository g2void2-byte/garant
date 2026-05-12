import { forwardRef, type HTMLAttributes } from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/cn";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  interactive?: boolean;
  inset?: boolean;
}

export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { className, interactive, inset, children, ...rest },
  ref,
) {
  if (interactive) {
    return (
      <motion.div
        ref={ref as any}
        whileTap={{ scale: 0.99 }}
        className={cn("bg-panel border border-border rounded-card p-4", inset && "bg-panel-2", className)}
        {...(rest as any)}
      >
        {children}
      </motion.div>
    );
  }
  return (
    <div
      ref={ref}
      className={cn("bg-panel border border-border rounded-card p-4", inset && "bg-panel-2", className)}
      {...rest}
    >
      {children}
    </div>
  );
});
