import { cn } from "@/lib/cn";

interface AvatarProps {
  name?: string;
  src?: string | null;
  size?: number;
  className?: string;
}

export function Avatar({ name = "?", src, size = 48, className }: AvatarProps) {
  const letter = name.replace(/^@/, "").trim().charAt(0).toUpperCase() || "?";
  return (
    <div
      style={{ width: size, height: size }}
      className={cn(
        "relative shrink-0 rounded-full overflow-hidden bg-panel-2 border border-border",
        "flex items-center justify-center text-text-muted font-bold",
        className,
      )}
    >
      {src ? (
        <img src={src} alt={name} className="w-full h-full object-cover" loading="lazy" decoding="async" />
      ) : (
        <span style={{ fontSize: size * 0.4 }}>{letter}</span>
      )}
    </div>
  );
}
