import { motion, type HTMLMotionProps } from "framer-motion";
import { forwardRef } from "react";
import { cn } from "@/lib/cn";
import { haptic } from "@/lib/tg";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

interface ButtonProps extends Omit<HTMLMotionProps<"button">, "ref"> {
  variant?: Variant;
  size?: Size;
  fullWidth?: boolean;
}

const VARIANT: Record<Variant, string> = {
  primary: "bg-accent text-accent-fg hover:brightness-95 active:brightness-90",
  secondary: "bg-panel-2 text-text border border-border hover:bg-[#28282A]",
  ghost: "bg-transparent text-text hover:bg-panel-2",
  danger: "bg-danger/15 text-danger border border-danger/40 hover:bg-danger/25",
};

const SIZE: Record<Size, string> = {
  sm: "h-9 px-3 text-sm rounded-xl",
  md: "h-12 px-4 text-base rounded-2xl",
  lg: "h-14 px-5 text-base rounded-2xl",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", fullWidth = false, className, onClick, children, ...rest },
  ref,
) {
  return (
    <motion.button
      ref={ref}
      whileTap={{ scale: 0.97 }}
      transition={{ type: "spring", stiffness: 500, damping: 30 }}
      className={cn(
        "inline-flex items-center justify-center gap-2 font-semibold select-none",
        "transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
        VARIANT[variant],
        SIZE[size],
        fullWidth && "w-full",
        className,
      )}
      onClick={(e) => {
        haptic(variant === "primary" ? "medium" : "light");
        onClick?.(e);
      }}
      {...rest}
    >
      {children}
    </motion.button>
  );
});
