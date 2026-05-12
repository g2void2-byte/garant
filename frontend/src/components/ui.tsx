import { motion } from "framer-motion";

export function Money({
  value,
  className = "",
}: {
  value: number;
  className?: string;
}) {
  const formatted = (Math.round(value * 100) / 100).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return <span className={className}>${formatted}</span>;
}

export function GradientText({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={
        "bg-gradient-to-r from-brand-200 via-brand-400 to-brand-500 bg-clip-text text-transparent " +
        className
      }
    >
      {children}
    </span>
  );
}

export function AnimatedNumber({ value }: { value: number }) {
  return (
    <motion.span
      key={value}
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <Money value={value} />
    </motion.span>
  );
}

export function Avatar({
  url,
  name,
  size = 40,
  className = "",
}: {
  url?: string | null;
  name?: string | null;
  size?: number;
  className?: string;
}) {
  const initials = (name ?? "?")
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  if (url) {
    return (
      <img
        src={url}
        alt={name ?? "user"}
        width={size}
        height={size}
        className={`rounded-full object-cover ring-2 ring-white/10 ${className}`}
      />
    );
  }
  return (
    <div
      style={{ width: size, height: size, fontSize: size * 0.4 }}
      className={`flex items-center justify-center rounded-full bg-gradient-to-br from-brand-300 to-brand-600 text-bg font-bold ring-2 ring-white/10 ${className}`}
    >
      {initials}
    </div>
  );
}

export function StatusPill({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    awaiting_payment: {
      label: "Ждёт оплаты",
      cls: "bg-amber-400/15 text-amber-300",
    },
    funded: { label: "В эскроу", cls: "bg-brand/15 text-brand-300" },
    completed: { label: "Завершена", cls: "bg-emerald-400/15 text-emerald-300" },
    cancelled: { label: "Отменена", cls: "bg-white/10 text-white/60" },
    disputed: { label: "Спор", cls: "bg-rose-500/15 text-rose-300" },
    refunded: { label: "Возврат", cls: "bg-sky-400/15 text-sky-300" },
    draft: { label: "Черновик", cls: "bg-white/10 text-white/60" },
  };
  const info = map[status] ?? { label: status, cls: "bg-white/10 text-white/70" };
  return <span className={`pill ${info.cls}`}>{info.label}</span>;
}
