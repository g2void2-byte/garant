import { CircleHelp } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  className?: string;
}

export function EmptyState({ icon, title, description, className }: EmptyStateProps) {
  return (
    <div
      className={cn("flex flex-col items-center justify-center text-center py-10 px-4 animate-fadein", className)}
    >
      <div className="size-12 rounded-full border border-dashed border-text-muted/40 grid place-items-center text-text-muted animate-breathe">
        {icon ?? <CircleHelp className="size-6" />}
      </div>
      <div className="mt-3 text-base font-semibold">{title}</div>
      {description && <div className="mt-1 text-sm text-text-muted max-w-[280px]">{description}</div>}
    </div>
  );
}
