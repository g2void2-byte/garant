import { Star, Wallet, Briefcase, BarChart3, ChevronRight } from "lucide-react";
import type { UserCardDto } from "@/api/types";
import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/cn";

interface StatProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  onClick?: () => void;
  accent?: boolean;
}

function Stat({ icon, label, value, onClick, accent }: StatProps) {
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
            accent ? "bg-accent/15 text-accent" : "bg-panel-2 text-text-muted",
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
            accent ? "text-accent" : "text-text",
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
  const ratingValue = Number(user.rating) || 0;
  const hasRating = ratingValue > 0 || user.reviews_count > 0;
  const ratingLabel = hasRating
    ? user.reviews_count > 0
      ? `${ratingValue.toFixed(1)} (${user.reviews_count})`
      : ratingValue.toFixed(1)
    : "—";
  return (
    <div className="grid grid-cols-2 gap-2">
      <Stat
        icon={<Star className="size-5" />}
        label="Рейтинг"
        value={ratingLabel}
        accent
      />
      <Stat
        icon={<Wallet className="size-5" />}
        label="Депозит"
        value={formatMoney(user.deposit)}
        accent
        onClick={onDepositClick}
      />
      <Stat icon={<Briefcase className="size-5" />} label="Сделок" value={String(user.deals_count)} />
      <Stat icon={<BarChart3 className="size-5" />} label="Сумма сделок" value={formatMoney(user.deals_sum)} />
    </div>
  );
}
