import { cn } from "@/lib/cn";

interface BadgePrefixProps {
  prefix?: string | null;
  className?: string;
}

const LABELS: Record<string, { text: string; cls: string }> = {
  admin: { text: "Админ", cls: "bg-accent text-accent-fg" },
  arbiter: { text: "Арбитр", cls: "bg-accent text-accent-fg" },
  vip: { text: "VIP", cls: "bg-accent text-accent-fg" },
};

const UNKNOWN_PREFIX = {
  text: "Роль неизвестна",
  cls: "bg-panel-2 text-text-muted",
};

export function BadgePrefix({ prefix, className }: BadgePrefixProps) {
  if (!prefix) return null;
  const conf = LABELS[prefix] ?? UNKNOWN_PREFIX;
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold leading-none",
        conf.cls,
        className,
      )}
    >
      {conf.text}
    </span>
  );
}
