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

/**
 * Continental `_button_vrakq_1` design:
 *   font-size: 16px, font-weight: 500, border-radius: 8px
 *   primary  → bg #fee600, color #000
 *   secondary → bg #383838, color #fff
 *   disabled  → bg #383838, color #5f5f60
 *   heights   → 44px (md/lg), 40px (sm)
 */
const VARIANT: Record<Variant, string> = {
  primary: "bg-accent text-black hover:brightness-95 active:brightness-90",
  secondary: "bg-secondary text-text hover:opacity-90 active:opacity-80",
  ghost: "bg-transparent text-text hover:bg-secondary/60",
  danger: "bg-danger text-white hover:opacity-90 active:opacity-80",
};

const SIZE: Record<Size, string> = {
  sm: "h-10 px-3 text-[15px]",
  md: "h-11 px-4 text-base",
  lg: "h-11 px-5 text-base",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", fullWidth = false, className, onClick, children, disabled, ...rest },
  ref,
) {
  return (
    <motion.button
      ref={ref}
      whileTap={{ scale: disabled ? 1 : 0.98 }}
      transition={{ type: "spring", stiffness: 500, damping: 30 }}
      disabled={disabled}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 font-medium select-none rounded-button",
        "transition-colors",
        VARIANT[variant],
        SIZE[size],
        fullWidth && "w-full",
        disabled && "!bg-secondary !text-text-disabled !cursor-not-allowed",
        className,
      )}
      onClick={(e) => {
        if (!disabled) haptic(variant === "primary" ? "medium" : "light");
        onClick?.(e);
      }}
      {...rest}
    >
      {children}
    </motion.button>
  );
});
