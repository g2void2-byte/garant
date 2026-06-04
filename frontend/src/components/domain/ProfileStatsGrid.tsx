import {
  Star,
  Wallet,
  Briefcase,
  BarChart3,
  ChevronRight,
  CheckCircle2,
  XCircle,
  AlertTriangle,
} from "lucide-react";
import type { UserCardDto } from "@/api/types";
import { formatCountValue, formatMoney, parseNonNegativeIntegerValue, parseRatingValue } from "@/lib/format";
import { cn } from "@/lib/cn";

type StatTone = "neutral" | "accent" | "success" | "danger" | "warning";

interface StatProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  onClick?: () => void;
  tone?: StatTone;
}

const TONE_BADGE: Record<StatTone, string> = {
  neutral: "bg-panel-2 text-text-muted",
  accent: "bg-accent/15 text-accent",
  success: "bg-emerald-500/15 text-emerald-500",
  danger: "bg-rose-500/15 text-rose-500",
  warning: "bg-amber-500/15 text-amber-500",
};

const TONE_VALUE: Record<StatTone, string> = {
  neutral: "text-text",
  accent: "text-accent",
  success: "text-emerald-500",
  danger: "text-rose-500",
  warning: "text-amber-500",
};

function Stat({ icon, label, value, onClick, tone = "neutral" }: StatProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full flex-col items-start gap-2 p-4 rounded-2xl bg-panel border border-border text-left",
        onClick && "active:scale-[.99] transition-transform",
      )}
    >
      <div className="flex w-full items-center justify-between">
        <span
          className={cn(
            "size-9 rounded-full grid place-items-center",
            TONE_BADGE[tone],
          )}
        >
          {icon}
        </span>
        {onClick && <ChevronRight className="size-4 text-text-muted" />}
      </div>
      <div className="mt-1 min-w-0 w-full">
        <div
          className={cn(
            "text-[22px] font-bold tracking-tight leading-none truncate",
            TONE_VALUE[tone],
          )}
        >
          {value}
        </div>
        <div className="mt-1.5 text-[13px] text-text-muted">{label}</div>
      </div>
    </button>
  );
}

export function ProfileStatsGrid({ user, onDepositClick }: { user: UserCardDto; onDepositClick?: () => void }) {
  // ``user.rating`` is whatever the serializer picked (manual override
  // if the admin set one, otherwise the auto-computed value). We want
  // a manually-set rating to surface even when ``reviews_count`` is
  // still 0, so the gate is "we have *something* to show" rather than
  // "we have reviews". The ``(N)`` suffix stays gated on review count.
  const ratingValue = parseRatingValue(user.rating);
  const reviewsCount = parseNonNegativeIntegerValue(user.reviews_count);
  const hasReviews = reviewsCount !== null && reviewsCount > 0;
  const ratingLabel = ratingValue !== null && (ratingValue > 0 || hasReviews)
    ? hasReviews
      ? `${ratingValue.toFixed(1)} (${reviewsCount})`
      : ratingValue.toFixed(1)
    : "—";
  return (
    <div className="grid grid-cols-2 gap-2">
      <Stat
        icon={<Star className="size-5" />}
        label="Рейтинг"
        value={ratingLabel}
        tone="accent"
      />
      <Stat
        icon={<Wallet className="size-5" />}
        label="Депозит"
        value={formatMoney(user.deposit)}
        tone="accent"
        onClick={onDepositClick}
      />
      <Stat
        icon={<Briefcase className="size-5" />}
        label="Сделок"
        value={formatCountValue(user.deals_count)}
      />
      <Stat
        icon={<BarChart3 className="size-5" />}
        label="Сумма сделок"
        value={formatMoney(user.deals_sum)}
      />
      {/* Item 11 — portfolio breakdown. Always render the three tiles
          so a fresh profile (0/0/0) reads as "no activity yet" rather
          than missing data; the colour cue still differentiates them
          when there are non-zero values. */}
      <Stat
        icon={<CheckCircle2 className="size-5" />}
        label="Успешных"
        value={formatCountValue(user.deals_success ?? 0)}
        tone="success"
      />
      <Stat
        icon={<XCircle className="size-5" />}
        label="Неуспешных"
        value={formatCountValue(user.deals_failed ?? 0)}
        tone="danger"
      />
      <Stat
        icon={<AlertTriangle className="size-5" />}
        label="Арбитражи"
        value={formatCountValue(user.deals_arbitrage ?? 0)}
        tone="warning"
      />
    </div>
  );
}
