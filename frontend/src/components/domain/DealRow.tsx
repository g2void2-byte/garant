import { ChevronRight } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import type { DealDto } from "@/api/types";
import { Avatar } from "@/components/ui/Avatar";
import { formatAmount, relativeTime } from "@/lib/format";
import { cn } from "@/lib/cn";
import { staggerDelay } from "@/lib/animate";
import { normalizeCurrencyCode } from "@/lib/currencyCodes";
import { normalizeUsernameRef, userProfilePath } from "@/lib/usernames";

const STATUS_LABEL: Record<string, { text: string; cls: string; icon: string }> = {
  pending_confirmation: {
    text: "Ожидает подтверждения",
    cls: "bg-[#48390F] text-accent",
    icon: "⏳",
  },
  pending_payment: { text: "Ожидает оплаты", cls: "bg-[#48390F] text-accent", icon: "💳" },
  pending_topup: { text: "Ожидает инвойс", cls: "bg-[#48390F] text-accent", icon: "💳" },
  in_progress: { text: "В работе", cls: "bg-success/15 text-success", icon: "▶️" },
  completed: { text: "Завершена", cls: "bg-success/15 text-success", icon: "🎉" },
  cancelled: { text: "Отменена", cls: "bg-danger/15 text-danger", icon: "❌" },
  cancelled_for_inactivity: {
    text: "Отмена за неактивность",
    cls: "bg-danger/15 text-danger",
    icon: "⏱️",
  },
  arbitration: { text: "Арбитраж", cls: "bg-accent/15 text-accent", icon: "⚖️" },
  resolved_for_buyer: {
    text: "В пользу покупателя",
    cls: "bg-success/15 text-success",
    icon: "🛒",
  },
  resolved_for_seller: {
    text: "В пользу продавца",
    cls: "bg-success/15 text-success",
    icon: "🏷️",
  },
  pending_cancellation: {
    text: "Запрошена отмена",
    cls: "bg-accent/15 text-accent",
    icon: "⏸️",
  },
};

export function DealRow({ deal, index = 0 }: { deal: DealDto; index?: number }) {
  const navigate = useNavigate();
  const status = STATUS_LABEL[deal.status] ?? { text: deal.status, cls: "bg-panel-2 text-text-muted", icon: "•" };
  // Item 21 — show the counterparty (i.e. the other side of the deal)
  // avatar + a "Профиль" deep-link. The seller's row in the buyer's
  // list and vice-versa.
  const rawCounterpartyUsername = deal.role === "buyer" ? deal.seller : deal.buyer;
  const counterpartyUsername = normalizeUsernameRef(rawCounterpartyUsername);
  const counterpartyPath = userProfilePath(counterpartyUsername);
  const counterpartyPhotoUrl =
    deal.role === "buyer" ? deal.seller_photo_url : deal.buyer_photo_url;
  const counterpartyLabel = deal.role === "buyer" ? "Продавец" : "Покупатель";
  const counterpartyName = counterpartyUsername || "Контрагент";
  const counterpartyText = counterpartyUsername
    ? `${counterpartyLabel}: @${counterpartyUsername}`
    : `${counterpartyLabel}: профиль недоступен`;
  const currencyCode = normalizeCurrencyCode(deal.currency_code);
  const amountCurrencyCode = currencyCode ?? "USDT";
  const openDeal = () => navigate(`/deals/${deal.id}`);
  const onDealKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openDeal();
    }
  };

  return (
    <div
      className="animate-fadein"
      style={staggerDelay(index, 25, 250)}
    >
      <div
        role="link"
        tabIndex={0}
        onClick={openDeal}
        onKeyDown={onDealKeyDown}
        className="block bg-panel border border-border rounded-card p-3 active:scale-[.99] transition-transform cursor-pointer focus:outline-none focus:ring-1 focus:ring-accent"
      >
        <div className="flex items-start gap-3">
          <Avatar
            name={counterpartyName}
            src={counterpartyPhotoUrl}
            size={40}
            className="mt-0.5"
          />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className={cn("inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold", status.cls)}>
                <span>{status.icon}</span>
                <span>{status.text}</span>
              </span>
              <span className="text-[11px] uppercase tracking-wide text-text-muted">#{deal.id}</span>
            </div>
            <div className="mt-2 font-semibold line-clamp-1">{deal.description}</div>
            <div className="mt-1 flex items-center gap-2 text-xs text-text-muted">
              <span className="truncate">{counterpartyText}</span>
              {deal.created_at && (
                <>
                  <span>·</span>
                  <span>{relativeTime(deal.created_at)}</span>
                </>
              )}
            </div>
            {counterpartyPath && (
              <div className="mt-2">
                <Link
                  to={counterpartyPath}
                  onClick={(e) => e.stopPropagation()}
                  onKeyDown={(e) => e.stopPropagation()}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-button bg-panel-2 border border-border text-[11px] text-text hover:bg-secondary active:scale-95 transition"
                >
                  Профиль
                </Link>
              </div>
            )}
          </div>
          <div className="text-right shrink-0">
            <div className="text-accent font-bold">
              {formatAmount(deal.amount, amountCurrencyCode)}
              {currencyCode && (
                <>
                  {" "}
                  <span className="text-text-muted text-xs font-normal">
                    {currencyCode}
                  </span>
                </>
              )}
            </div>
            <div className="mt-1 inline-flex items-center text-text-muted text-xs">
              {deal.role === "buyer" ? "Покупка" : "Продажа"} <ChevronRight className="size-3" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
