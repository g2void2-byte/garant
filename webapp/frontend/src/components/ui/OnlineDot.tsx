import { cn } from "@/lib/cn";

export function OnlineDot({ online, className }: { online: boolean; className?: string }) {
  return (
    <span
      className={cn(
        "inline-block size-2 rounded-full",
        online ? "bg-success shadow-[0_0_8px_var(--success)]" : "bg-text-muted/40",
        className,
      )}
    />
  );
}
