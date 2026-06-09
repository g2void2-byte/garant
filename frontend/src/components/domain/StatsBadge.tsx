import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Users, Handshake, DollarSign } from "lucide-react";
import { api } from "@/api/client";
import { qk } from "@/api/queryKeys";
import { parseDecimalValue, parseNonNegativeIntegerValue } from "@/lib/format";

interface PublicStats {
  users: unknown;
  deals: unknown;
  total_usd: unknown;
}

/** Smoothly count from 0 to ``target`` over ~1.2s. */
function useCountUp(target: number, durationMs = 1200): number {
  const [value, setValue] = useState(0);
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number | null>(null);
  const valueRef = useRef(0);

  useEffect(() => {
    valueRef.current = value;
  }, [value]);

  useEffect(() => {
    const startValue = valueRef.current;
    startRef.current = null;
    const animate = (now: number) => {
      if (startRef.current === null) startRef.current = now;
      const t = Math.min(1, (now - startRef.current) / durationMs);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - t, 3);
      const next = startValue + (target - startValue) * eased;
      valueRef.current = next;
      setValue(next);
      if (t < 1) rafRef.current = requestAnimationFrame(animate);
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [target, durationMs]);

  return value;
}

function formatCompact(n: number): string {
  if (n < 1000) return Math.round(n).toLocaleString("ru-RU");
  if (n < 1_000_000)
    return (
      (Math.round(n / 100) / 10).toLocaleString("ru-RU", {
        maximumFractionDigits: 1,
      }) + "K"
    );
  return (
    (Math.round(n / 100_000) / 10).toLocaleString("ru-RU", {
      maximumFractionDigits: 1,
    }) + "M"
  );
}

function formatUsd(n: number): string {
  if (n < 1000) return "$" + Math.round(n).toLocaleString("ru-RU");
  if (n < 1_000_000)
    return (
      "$" +
      (Math.round(n / 100) / 10).toLocaleString("ru-RU", {
        maximumFractionDigits: 1,
      }) +
      "K"
    );
  return (
    "$" +
    (Math.round(n / 100_000) / 10).toLocaleString("ru-RU", {
      maximumFractionDigits: 1,
    }) +
    "M"
  );
}

function parsePublicCount(value: unknown): number {
  return parseNonNegativeIntegerValue(value) ?? 0;
}

function parsePublicUsd(value: unknown): number {
  if (value !== null && value !== undefined && typeof value !== "number" && typeof value !== "string") {
    return 0;
  }
  const parsed = parseDecimalValue(value);
  return parsed !== null && parsed >= 0 ? parsed : 0;
}

interface StatsBadgeProps {
  /** Optional title above the stats row. */
  title?: string;
  /** Optional subtitle below the stats row. */
  subtitle?: string;
  /** Visual variant. ``"hero"`` is large + glow, ``"compact"`` is denser. */
  variant?: "hero" | "compact";
  /**
   * Override stats values. When provided, the badge skips the
   * ``/api/stats/public`` fetch and renders these values directly —
   * useful for the admin-settings live preview where the admin is
   * editing the values in the form.
   */
  stats?: PublicStats;
}

/**
 * Animated public-stats badge intended for the FAQ page and an
 * admin-settings preview. Pulls ``/api/stats/public`` and animates the
 * three headline counters (users, deals, total USD volume).
 *
 * Visual treatment:
 * - gradient border + soft accent glow behind the card
 * - pulsing accent ring on each stat icon
 * - count-up animation on every value change
 * - skeleton placeholders while loading
 */
export function StatsBadge({
  title = "Гарант в цифрах",
  subtitle = "Живая статистика всей платформы",
  variant = "hero",
  stats,
}: StatsBadgeProps) {
  const query = useQuery<PublicStats>({
    queryKey: qk.publicStats(),
    queryFn: () => api.get("api/stats/public").json(),
    staleTime: 30_000,
    refetchInterval: 60_000,
    enabled: stats === undefined,
  });
  const data = stats ?? query.data;
  const isLoading = stats === undefined && query.isLoading;

  const users = useCountUp(parsePublicCount(data?.users));
  const deals = useCountUp(parsePublicCount(data?.deals));
  const usd = useCountUp(parsePublicUsd(data?.total_usd));

  const isHero = variant === "hero";

  return (
    <div className="relative">
      {/* Glow */}
      <div
        aria-hidden
        className="absolute -inset-3 rounded-[28px] bg-accent/20 blur-2xl opacity-60 pointer-events-none"
      />
      <div
        aria-hidden
        className="absolute -inset-1 rounded-[24px] bg-gradient-to-br from-accent/40 via-accent/0 to-accent/30 blur-md pointer-events-none"
      />

      <div
        className={[
          "relative rounded-[20px] border border-border/60 bg-gradient-to-br from-panel via-panel to-panel-2 overflow-hidden",
          isHero ? "px-5 py-5" : "px-4 py-3",
        ].join(" ")}
      >
        {/* Decorative shimmer line */}
        <div
          aria-hidden
          className="absolute -top-px left-0 right-0 h-px bg-gradient-to-r from-transparent via-accent/80 to-transparent"
        />

        {title && (
          <div className="text-[15px] font-bold text-text mb-0.5">{title}</div>
        )}
        {subtitle && (
          <div className="text-xs text-text-muted mb-4">{subtitle}</div>
        )}

        <div className="grid grid-cols-3 gap-2">
          <StatCell
            icon={<Users size={isHero ? 18 : 16} />}
            label="Пользователи"
            value={isLoading ? "…" : formatCompact(users)}
            variant={variant}
          />
          <StatCell
            icon={<Handshake size={isHero ? 18 : 16} />}
            label="Сделок"
            value={isLoading ? "…" : formatCompact(deals)}
            variant={variant}
          />
          <StatCell
            icon={<DollarSign size={isHero ? 18 : 16} />}
            label="Объём"
            value={isLoading ? "…" : formatUsd(usd)}
            variant={variant}
          />
        </div>
      </div>
    </div>
  );
}

function StatCell({
  icon,
  label,
  value,
  variant,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  variant: "hero" | "compact";
}) {
  const isHero = variant === "hero";
  return (
    <div
      className={[
        "relative flex flex-col items-center justify-center rounded-[14px] bg-panel-2/80 backdrop-blur-sm border border-border/50",
        isHero ? "py-3 px-2" : "py-2 px-1.5",
      ].join(" ")}
    >
      <div
        className={[
          "relative flex items-center justify-center rounded-full bg-accent/15 text-accent mb-1.5",
          isHero ? "w-8 h-8" : "w-6 h-6",
        ].join(" ")}
      >
        <span
          aria-hidden
          className="absolute inset-0 rounded-full bg-accent/30 animate-ping opacity-60"
        />
        <span className="relative">{icon}</span>
      </div>
      <div
        className={[
          "font-bold text-text leading-none tabular-nums",
          isHero ? "text-lg" : "text-base",
        ].join(" ")}
      >
        {value}
      </div>
      <div
        className={[
          "text-text-muted mt-1 leading-none text-center",
          isHero ? "text-[11px]" : "text-[10px]",
        ].join(" ")}
      >
        {label}
      </div>
    </div>
  );
}
