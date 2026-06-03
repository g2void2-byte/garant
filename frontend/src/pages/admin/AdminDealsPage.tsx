import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Filter, ChevronLeft, ChevronRight, AlertTriangle, Gavel, Search } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { AdminHeader } from "@/components/layout/AdminHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { useAdminDeals } from "@/api/admin/hooks";
import { parseDecimal } from "@/lib/format";
import { parsePositiveIntRouteParam } from "@/lib/routeParams";
import type { AdminDealListItemDto, AdminListDealsQuery } from "@/api/types";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";
import { formatAdminUsername } from "./format";

// Audit L-10 — ``null`` is the in-component sentinel for "all statuses";
// the legacy ``"any"`` string is gone from both UI state and the URL.
const STATUS_LABEL: Record<string, string> = {
  cancelled: "Отменена",
  pending_confirmation: "Подтверждение",
  pending_payment: "Ожидание оплаты",
  pending_topup: "Ожидание инвойса",
  in_progress: "В работе",
  completed: "Завершена",
  arbitration: "Арбитраж",
  resolved_for_buyer: "В пользу покупателя",
  resolved_for_seller: "В пользу продавца",
  pending_cancellation: "Запрошена отмена",
  cancelled_for_inactivity: "Отменена по неактивности",
};

const FILTERABLE_STATUS_VALUES = [
  "cancelled",
  "pending_confirmation",
  "pending_topup",
  "in_progress",
  "completed",
  "arbitration",
  "resolved_for_buyer",
  "resolved_for_seller",
  "pending_cancellation",
  "cancelled_for_inactivity",
] as const;

const STATUSES: Array<{ value: string | null; label: string }> = [
  { value: null, label: "Все" },
  ...FILTERABLE_STATUS_VALUES.map((value) => ({ value, label: STATUS_LABEL[value] })),
];

const FILTERABLE_STATUS_SET = new Set<string>(FILTERABLE_STATUS_VALUES);
const DECIMAL_PARAM_RE = /^\d+(?:\.\d+)?$|^\.\d+$/;
const CURRENCY_PARAM_RE = /^[A-Z0-9]{1,16}$/;

function parseStatusParam(value: string | null): AdminListDealsQuery["status"] {
  if (!value || !FILTERABLE_STATUS_SET.has(value)) return undefined;
  return value as AdminListDealsQuery["status"];
}

function parsePageParam(value: string | null): number {
  return parsePositiveIntRouteParam(value ?? undefined) ?? 1;
}

function parseAmountParam(value: string | null): number | undefined {
  const trimmed = (value ?? "").trim();
  if (!trimmed || !DECIMAL_PARAM_RE.test(trimmed)) return undefined;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
}

function parseCurrencyParam(value: string | null): string | undefined {
  const code = (value ?? "").trim().toUpperCase();
  return CURRENCY_PARAM_RE.test(code) ? code : undefined;
}

/**
 * Continental admin deals list.
 *
 * URL-driven filters: ``?status=in_progress&currency=USDT&has_arbitration=true``
 * so dashboards / deep-links from the user detail page can seed the
 * filter sheet without state plumbing.
 */
export default function AdminDealsPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [filterOpen, setFilterOpen] = useState(false);
  const [draftCurrency, setDraftCurrency] = useState(params.get("currency") ?? "");
  const [draftMin, setDraftMin] = useState(params.get("min_amount") ?? "");
  const [draftMax, setDraftMax] = useState(params.get("max_amount") ?? "");

  // Audit L-10 — ``status`` is ``string | undefined``; ``undefined`` is the
  // "no filter" sentinel and translates to an omitted URL param.
  const status = parseStatusParam(params.get("status"));
  const currency = parseCurrencyParam(params.get("currency"));
  const min_amount = parseAmountParam(params.get("min_amount"));
  const max_amount = parseAmountParam(params.get("max_amount"));
  const has_arbitration = params.get("has_arbitration") === "true" || undefined;
  const has_cancel_request = params.get("has_cancel_request") === "true" || undefined;
  const page = parsePageParam(params.get("page"));

  const query: AdminListDealsQuery = {
    status,
    currency,
    min_amount,
    max_amount,
    has_arbitration,
    has_cancel_request,
    page,
    page_size: 20,
  };
  const { data, isLoading } = useAdminDeals(query);

  const __guard = useAdminRedirect();
  if (!__guard.shouldRender) return null;

  const update = (next: Record<string, string | number | boolean | undefined | null>) => {
    const sp = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      // Audit L-10 — ``null``/``undefined``/empty/``false`` all mean
      // "clear the filter". The legacy ``"any"`` sentinel is gone.
      if (v === undefined || v === null || v === "" || v === false) {
        sp.delete(k);
      } else if (typeof v === "number" && !Number.isFinite(v)) {
        sp.delete(k);
      } else {
        sp.set(k, String(v));
      }
    }
    if (!("page" in next)) sp.delete("page");
    setParams(sp, { replace: true });
  };

  const items: AdminDealListItemDto[] = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / 20));

  return (
    <Page showBack onBack={() => navigate(-1)}>
      <AdminHeader
        title="Сделки"
        subtitle={data ? `${total} всего` : undefined}
        right={
          <button
            type="button"
            onClick={() => setFilterOpen(true)}
            className="rounded-button bg-panel p-2 text-text-muted active:scale-95"
            aria-label="Фильтры"
          >
            <Filter size={18} />
          </button>
        }
      />

      {/* Status chips — horizontally scrollable */}
      <div className="px-4 -mx-1 overflow-x-auto no-scrollbar flex gap-2 mb-3 pb-1">
        {STATUSES.map((s) => (
          <button
            key={s.value ?? "__none__"}
            type="button"
            onClick={() => update({ status: s.value ?? undefined })}
            className={`whitespace-nowrap rounded-full px-3 py-1.5 text-xs border transition-colors ${
              (status ?? null) === s.value
                ? "bg-accent text-black border-accent"
                : "bg-panel text-text-muted border-border hover:bg-panel-2"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* Active filter chips */}
      {(currency || min_amount !== undefined || max_amount !== undefined || has_arbitration || has_cancel_request) && (
        <div className="px-4 -mx-1 overflow-x-auto no-scrollbar flex gap-2 mb-3 pb-1">
          {currency && (
            <FilterChip onRemove={() => update({ currency: undefined })}>
              Валюта: {currency}
            </FilterChip>
          )}
          {min_amount !== undefined && (
            <FilterChip onRemove={() => update({ min_amount: undefined })}>
              Мин: {min_amount}
            </FilterChip>
          )}
          {max_amount !== undefined && (
            <FilterChip onRemove={() => update({ max_amount: undefined })}>
              Макс: {max_amount}
            </FilterChip>
          )}
          {has_arbitration && (
            <FilterChip onRemove={() => update({ has_arbitration: undefined })}>
              <Gavel size={11} className="inline -mt-0.5" /> Арбитраж
            </FilterChip>
          )}
          {has_cancel_request && (
            <FilterChip onRemove={() => update({ has_cancel_request: undefined })}>
              <AlertTriangle size={11} className="inline -mt-0.5" /> Запрос отмены
            </FilterChip>
          )}
        </div>
      )}

      {isLoading ? (
        <div className="px-4 space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Search size={20} />}
          title="Сделок не найдено"
          description="Попробуйте изменить фильтры."
        />
      ) : (
        <ul className="px-4 space-y-2">
          {items.map((deal, idx) => (
            <li
              key={deal.id}
              className="animate-fadein"
              style={{ animationDelay: `${Math.min(idx, 8) * 30}ms` }}
            >
              <DealRow deal={deal} onOpen={() => navigate(`/admin/deals/${deal.id}`)} />
            </li>
          ))}
        </ul>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 mt-4 mb-2 text-sm">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => update({ page: page - 1 })}
            className="p-2 rounded-button bg-panel disabled:opacity-40 active:scale-95"
            aria-label="Назад"
          >
            <ChevronLeft size={18} />
          </button>
          <span className="text-text-muted">
            {page} / {totalPages}
          </span>
          <button
            type="button"
            disabled={page >= totalPages}
            onClick={() => update({ page: page + 1 })}
            className="p-2 rounded-button bg-panel disabled:opacity-40 active:scale-95"
            aria-label="Вперёд"
          >
            <ChevronRight size={18} />
          </button>
        </div>
      )}

      <Sheet open={filterOpen} onClose={() => setFilterOpen(false)} title="Фильтры">
        <div className="space-y-4">
          <label className="block text-sm">
            <span className="text-text-muted">Валюта</span>
            <input
              value={draftCurrency}
              onChange={(e) => setDraftCurrency(e.target.value.toUpperCase())}
              placeholder="USDT, BTC..."
              className="mt-1 w-full bg-panel rounded-button px-3 py-2"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm">
              <span className="text-text-muted">Мин. сумма</span>
              <input
                type="number"
                inputMode="decimal"
                value={draftMin}
                onChange={(e) => setDraftMin(e.target.value)}
                className="mt-1 w-full bg-panel rounded-button px-3 py-2"
              />
            </label>
            <label className="block text-sm">
              <span className="text-text-muted">Макс. сумма</span>
              <input
                type="number"
                inputMode="decimal"
                value={draftMax}
                onChange={(e) => setDraftMax(e.target.value)}
                className="mt-1 w-full bg-panel rounded-button px-3 py-2"
              />
            </label>
          </div>
          <div className="space-y-2">
            <ToggleRow
              label="Только с арбитражем"
              checked={!!has_arbitration}
              onChange={(v) => update({ has_arbitration: v || undefined })}
            />
            <ToggleRow
              label="Только с запросом отмены"
              checked={!!has_cancel_request}
              onChange={(v) => update({ has_cancel_request: v || undefined })}
            />
          </div>
          <div className="flex gap-2 pt-2">
            <Button
              variant="secondary"
              fullWidth
              onClick={() => {
                setDraftCurrency("");
                setDraftMin("");
                setDraftMax("");
                update({
                  currency: undefined,
                  min_amount: undefined,
                  max_amount: undefined,
                  has_arbitration: undefined,
                  has_cancel_request: undefined,
                });
                setFilterOpen(false);
              }}
            >
              Сбросить
            </Button>
            <Button
              fullWidth
              onClick={() => {
                update({
                  currency: parseCurrencyParam(draftCurrency),
                  min_amount: parseAmountParam(draftMin),
                  max_amount: parseAmountParam(draftMax),
                });
                setFilterOpen(false);
              }}
            >
              Применить
            </Button>
          </div>
        </div>
      </Sheet>
    </Page>
  );
}

function FilterChip({ children, onRemove }: { children: React.ReactNode; onRemove: () => void }) {
  return (
    <button
      type="button"
      onClick={onRemove}
      className="whitespace-nowrap rounded-full px-3 py-1.5 text-xs bg-accent/10 text-accent border border-accent/30 active:scale-95"
    >
      {children} ×
    </button>
  );
}

function ToggleRow({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between bg-panel rounded-button px-3 py-2.5 cursor-pointer select-none">
      <span className="text-sm">{label}</span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="size-4 accent-accent"
      />
    </label>
  );
}

function DealRow({ deal, onOpen }: { deal: AdminDealListItemDto; onOpen: () => void }) {
  const accent =
    deal.status === "arbitration"
      ? "border-danger/40"
      : deal.status === "pending_cancellation"
      ? "border-warning/40"
      : deal.status === "completed" || deal.status === "resolved_for_seller" || deal.status === "resolved_for_buyer"
      ? "border-success/30"
      : "border-border";

  return (
    <button
      type="button"
      onClick={onOpen}
      className={`w-full text-left bg-panel rounded-card p-3 flex items-center gap-3 border ${accent} hover:bg-panel-2 transition-colors active:scale-[0.98]`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 text-sm font-semibold">
          <span>#{deal.id}</span>
          <span className="text-text-muted">·</span>
          <span className="text-text-muted truncate">
            {formatAdminUsername(deal.buyer_username)} → {formatAdminUsername(deal.seller_username)}
          </span>
        </div>
        <div className="mt-0.5 text-xs text-text-muted flex items-center gap-2 flex-wrap">
          <span className="font-medium text-text">
            {parseDecimal(deal.amount).toFixed(
              deal.currency_code === "USDT" || deal.currency_code === "USDC" ? 2 : 6,
            )}{" "}
            {deal.currency_code ?? "USD"}
          </span>
          <span>·</span>
          <span>{STATUS_LABEL[deal.status] ?? deal.status}</span>
          {deal.has_arbitration && (
            <>
              <span>·</span>
              <span className="text-danger flex items-center gap-0.5">
                <Gavel size={11} /> арбитраж
              </span>
            </>
          )}
          {deal.has_cancel_request && (
            <>
              <span>·</span>
              <span className="text-warning flex items-center gap-0.5">
                <AlertTriangle size={11} /> отмена
              </span>
            </>
          )}
        </div>
      </div>
      <ChevronRight size={16} className="text-text-muted shrink-0" />
    </button>
  );
}
