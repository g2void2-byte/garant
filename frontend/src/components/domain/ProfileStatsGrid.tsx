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
        "flex w-full items-center justify-between p-3 rounded-2xl bg-panel border border-border text-left",
        onClick && "active:scale-[.99] transition-transform",
      )}
    >
      <div className="flex items-center gap-3 min-w-0">
        <div className={cn("size-10 rounded-full grid place-items-center", accent ? "bg-accent/15 text-accent" : "bg-panel-2 text-text-muted")}>{icon}</div>
        <div className="min-w-0">
          <div className="text-xs text-text-muted">{label}</div>
          <div className={cn("font-bold", accent && "text-accent")}>{value}</div>
        </div>
      </div>
      {onClick && <ChevronRight className="size-4 text-text-muted" />}
    </button>
  );
}

export function ProfileStatsGrid({ user, onDepositClick }: { user: UserCardDto; onDepositClick?: () => void }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      <Stat
        icon={<Star className="size-5" />}
        label="Рейтинг"
        value={user.reviews_count ? `★ ${user.rating.toFixed(1)} (${user.reviews_count})` : "Нет оценок"}
        accent
      />
      <Stat icon={<Wallet className="size-5" />} label="Депозит" value={formatMoney(user.deposit)} accent onClick={onDepositClick} />
      <Stat icon={<Briefcase className="size-5" />} label="Сделок" value={String(user.deals_count)} />
      <Stat icon={<BarChart3 className="size-5" />} label="Сумма сделок" value={formatMoney(user.deals_sum)} />
    </div>
  );
}
