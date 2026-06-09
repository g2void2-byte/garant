import { ChevronRight } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import type { DealDto } from "@/api/types";
import { Avatar } from "@/components/ui/Avatar";
import { formatAmount, relativeTime } from "@/lib/format";
import { cn } from "@/lib/cn";
import { staggerDelay } from "@/lib/animate";
import { normalizeCurrencyCode } from "@/lib/currencyCodes";
import { parsePositiveIntValue } from "@/lib/routeParams";
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

const UNKNOWN_DEAL_STATUS = "Статус неизвестен";

export function DealRow({ deal, index = 0 }: { deal: DealDto; index?: number }) {
  const navigate = useNavigate();
  const status = STATUS_LABEL[deal.status] ?? {
    text: UNKNOWN_DEAL_STATUS,
    cls: "bg-panel-2 text-text-muted",
    icon: "•",
  };
  // Item 21 — show the counterparty (i.e. the other side of the deal)
  // avatar + a "Профиль" deep-link. The seller's row in the buyer's
  // list and vice-versa.
  const isBuyerRole = deal.role === "buyer";
  const isSellerRole = deal.role === "seller";
  const rawCounterpartyUsername = isBuyerRole
    ? deal.seller
    : isSellerRole
      ? deal.buyer
      : null;
  const counterpartyUsername = normalizeUsernameRef(rawCounterpartyUsername);
  const counterpartyPath = userProfilePath(counterpartyUsername);
  const counterpartyPhotoUrl = isBuyerRole
    ? deal.seller_photo_url
    : isSellerRole
      ? deal.buyer_photo_url
      : null;
  const counterpartyLabel = isBuyerRole
    ? "Продавец"
    : isSellerRole
      ? "Покупатель"
      : "Контрагент";
  const dealKindLabel = isBuyerRole ? "Покупка" : isSellerRole ? "Продажа" : "Сделка";
  const counterpartyName = counterpartyUsername || "Контрагент";
  const counterpartyText = counterpartyUsername
    ? `${counterpartyLabel}: @${counterpartyUsername}`
    : `${counterpartyLabel}: профиль недоступен`;
  const currencyCode = normalizeCurrencyCode(deal.currency_code);
  const amountCurrencyCode = currencyCode ?? "USDT";
  const dealId = parsePositiveIntValue(deal.id);
  const openDeal = () => {
    if (dealId !== undefined) navigate(`/deals/${dealId}`);
  };
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
        role={dealId !== undefined ? "link" : undefined}
        tabIndex={dealId !== undefined ? 0 : undefined}
        onClick={dealId !== undefined ? openDeal : undefined}
        onKeyDown={dealId !== undefined ? onDealKeyDown : undefined}
        aria-disabled={dealId === undefined ? true : undefined}
        className={cn(
          "block bg-panel border border-border rounded-card p-3 transition-transform",
          dealId !== undefined
            ? "active:scale-[.99] cursor-pointer focus:outline-none focus:ring-1 focus:ring-accent"
            : "cursor-default",
        )}
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
              <span className="text-[11px] uppercase tracking-wide text-text-muted">#{dealId ?? "\u2014"}</span>
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
              {dealKindLabel} <ChevronRight className="size-3" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
