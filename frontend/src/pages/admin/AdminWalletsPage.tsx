import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronLeft, ChevronRight, Minus, Plus, Search, Wallet } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { AdminHeader } from "@/components/layout/AdminHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { useToast } from "@/components/ui/Toast";
import {
  useAdminAdjustBalance,
  useAdminCurrencies,
  useAdminCurrencyRates,
  useAdminUpsertCurrencyRate,
  useAdminWallets,
} from "@/api/admin/hooks";
import { parseDecimal } from "@/lib/format";
import type {
  AdminCurrencyRateDto,
  AdminUserBalanceDto,
  AdminWalletListItemDto,
} from "@/api/types";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";

const PAGE_SIZE = 50;

/**
 * `/admin/wallets` — user-balance inspector + manual credit/debit.
 *
 * Search debounces on Enter / blur (matching `AdminUsersPage`). Tapping
 * a row opens a sheet that lets the admin select a currency, set the
 * delta (signed) and an optional reason. Reason is *not* required per
 * the user's spec.
 */
export default function AdminWalletsPage() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [draftQ, setDraftQ] = useState("");
  const [page, setPage] = useState(1);
  const { data, isLoading } = useAdminWallets({ q, page, page_size: PAGE_SIZE });
  const [target, setTarget] = useState<AdminWalletListItemDto | null>(null);
  const [ratesOpen, setRatesOpen] = useState(false);

  const __guard = useAdminRedirect();
  if (!__guard.shouldRender) return null;

  return (
    <Page showBack onBack={() => navigate(-1)}>
      <AdminHeader
        title="Балансы"
        subtitle={data ? `${data.total} пользователей` : undefined}
      />
      <div className="px-4 mb-3">
        <div className="flex items-center gap-2">
          <div className="flex flex-1 items-center gap-2 bg-panel rounded-button px-3 py-2">
            <Search size={16} className="text-text-muted" />
            <input
              value={draftQ}
              onChange={(e) => setDraftQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  setQ(draftQ.trim());
                  setPage(1);
                }
              }}
              onBlur={() => {
                if (draftQ.trim() !== q) {
                  setQ(draftQ.trim());
                  setPage(1);
                }
              }}
              placeholder="@username"
              className="flex-1 bg-transparent outline-none text-sm"
            />
          </div>
          <Button type="button" size="sm" variant="secondary" onClick={() => setRatesOpen(true)}>
            USD
          </Button>
        </div>
      </div>
      <div className="px-4 space-y-2 pb-24">
        {isLoading ? (
          Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-card" />
          ))
        ) : data?.items.length === 0 ? (
          <p className="text-sm text-text-muted text-center py-12">
            Ничего не найдено
          </p>
        ) : (
          data?.items.map((it, _idx) => (
            <button
              key={it.user_id}
              type="button"
              onClick={() => setTarget(it)}
              className="w-full text-left bg-panel rounded-card p-3 hover:bg-panel-2 transition active:scale-[0.98]"
            >
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-panel-2 overflow-hidden flex-shrink-0">
                  {it.photo_url && (
                    <img src={it.photo_url} alt="" className="w-full h-full object-cover" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{it.display_name}</div>
                  <div className="text-xs text-text-muted truncate">
                    @{it.username ?? "—"}
                  </div>
                </div>
                <Wallet size={16} className="text-text-muted" />
              </div>
              {it.total_usd_estimate !== undefined && it.total_usd_estimate !== null ? (
                <div className="mt-2 text-xs text-success">
                  USD estimate: ${parseDecimal(it.total_usd_estimate).toFixed(2)}
                </div>
              ) : it.usd_estimate_missing_rates?.length ? (
                <div className="mt-2 text-xs text-warning">
                  No USD rate: {it.usd_estimate_missing_rates.join(", ")}
                </div>
              ) : null}
              {(() => {
                // Filter once so we know both whether to render the grid
                // at all *and* what to put in it — otherwise users with
                // all-zero balances would see an empty grid container
                // that looks like a broken layout.
                const nonZero = it.balances.filter((b) => parseDecimal(b.total) > 0);
                if (nonZero.length === 0) {
                  return (
                    <div className="mt-2 text-xs text-text-muted italic">
                      Балансов нет
                    </div>
                  );
                }
                return (
                  <div className="mt-3 grid grid-cols-2 gap-1.5">
                    {nonZero.slice(0, 4).map((b) => {
                      const amt = parseDecimal(b.amount);
                      const locked = parseDecimal(b.locked);
                      return (
                        <div
                          key={b.currency_id}
                          className="text-xs bg-panel-2 rounded-button px-2 py-1.5"
                        >
                          <div className="text-text-muted">{b.currency_code}</div>
                          <div className="font-mono">
                            {amt.toFixed(b.decimals)}
                            {locked > 0 && (
                              <span className="text-warning ml-1">
                                (+{locked.toFixed(b.decimals)} лок.)
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
            </button>
          ))
        )}
      </div>
      {data && data.total > data.page_size && (
        <Pagination
          page={page}
          totalPages={Math.max(1, Math.ceil(data.total / data.page_size))}
          onPage={setPage}
        />
      )}

      <Sheet
        open={!!target}
        onClose={() => setTarget(null)}
        title={target ? `Корректировка: ${target.display_name}` : undefined}
      >
        {target && (
          <>
            <BalanceOverview target={target} />
            <AdjustForm target={target} onClose={() => setTarget(null)} />
          </>
        )}
      </Sheet>
      <Sheet open={ratesOpen} onClose={() => setRatesOpen(false)} title="USD rates">
        <RatesForm onClose={() => setRatesOpen(false)} />
      </Sheet>
    </Page>
  );
}

function Pagination({
  page,
  totalPages,
  onPage,
}: {
  page: number;
  totalPages: number;
  onPage: (page: number) => void;
}) {
  return (
    <div className="flex items-center justify-center gap-3 mt-1 mb-4 text-sm">
      <button
        type="button"
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
        className="p-2 rounded-button bg-panel disabled:opacity-40 active:scale-95"
        aria-label={"\u041d\u0430\u0437\u0430\u0434"}
      >
        <ChevronLeft size={18} />
      </button>
      <span className="text-text-muted">
        {page} / {totalPages}
      </span>
      <button
        type="button"
        disabled={page >= totalPages}
        onClick={() => onPage(page + 1)}
        className="p-2 rounded-button bg-panel disabled:opacity-40 active:scale-95"
        aria-label={"\u0412\u043f\u0435\u0440\u0451\u0434"}
      >
        <ChevronRight size={18} />
      </button>
    </div>
  );
}

function BalanceOverview({ target }: { target: AdminWalletListItemDto }) {
  const nonZero = target.balances.filter((b) => parseDecimal(b.total) > 0);
  return (
    <div className="mb-4 rounded-card border border-border bg-panel p-3">
      <div className="text-xs uppercase tracking-wide text-text-muted">Balances</div>
      {nonZero.length === 0 ? (
        <div className="mt-2 text-xs text-text-muted italic">No balances</div>
      ) : (
        <div className="mt-3 grid grid-cols-2 gap-1.5">
          {nonZero.map((balance) => (
            <BalancePill key={balance.currency_id} balance={balance} />
          ))}
        </div>
      )}
    </div>
  );
}

function BalancePill({ balance }: { balance: AdminUserBalanceDto }) {
  const amt = parseDecimal(balance.amount);
  const locked = parseDecimal(balance.locked);
  return (
    <div className="text-xs bg-panel-2 rounded-button px-2 py-1.5">
      <div className="text-text-muted">{balance.currency_code}</div>
      <div className="font-mono">
        {amt.toFixed(balance.decimals)}
        {locked > 0 && (
          <span className="text-warning ml-1">
            (+{locked.toFixed(balance.decimals)} lock)
          </span>
        )}
      </div>
    </div>
  );
}

function RatesForm({ onClose }: { onClose: () => void }) {
  const { data: currencies } = useAdminCurrencies();
  const { data: rates } = useAdminCurrencyRates();
  const upsert = useAdminUpsertCurrencyRate();
  const toast = useToast();
  const [currency, setCurrency] = useState("USDT");
  const current = (rates ?? []).find((r: AdminCurrencyRateDto) => r.currency_code === currency);
  const [rate, setRate] = useState<string | null>(null);
  const [source, setSource] = useState("manual");
  const value = rate ?? (current ? String(current.usd_rate) : "");

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {(currencies ?? []).map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => {
              setCurrency(c.code);
              setRate(null);
              setSource((rates ?? []).find((r) => r.currency_code === c.code)?.source ?? "manual");
            }}
            className={`rounded-button px-3 py-1.5 text-sm transition ${
              c.code === currency ? "bg-accent text-accent-fg font-medium" : "bg-panel-2 text-text-muted"
            }`}
          >
            {c.code}
          </button>
        ))}
      </div>
      <Input
        label={`USD rate for ${currency}`}
        inputMode="decimal"
        value={value}
        onChange={(e) => setRate(e.target.value)}
      />
      <Input label="Source" value={source} onChange={(e) => setSource(e.target.value)} />
      {current?.observed_at && (
        <div className="text-xs text-text-muted">Last observed: {new Date(current.observed_at).toLocaleString()}</div>
      )}
      <Button
        type="button"
        fullWidth
        disabled={upsert.isPending || !Number(value)}
        onClick={async () => {
          try {
            await upsert.mutateAsync({ currency_code: currency, usd_rate: Number(value), source: source.trim() || "manual" });
            toast.show({ kind: "success", title: "USD rate saved" });
            setRate(null);
            onClose();
          } catch (e) {
            toast.show({ kind: "error", title: "Error", body: (e as Error).message });
          }
        }}
      >
        Save rate
      </Button>
    </div>
  );
}

function AdjustForm({
  target,
  onClose,
}: {
  target: AdminWalletListItemDto;
  onClose: () => void;
}) {
  const { data: currencies } = useAdminCurrencies();
  const [currency, setCurrency] = useState(
    target.balances.find((b) => parseDecimal(b.total) > 0)?.currency_code ?? "USDT",
  );
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const toast = useToast();
  const adjust = useAdminAdjustBalance(target.user_id);
  const allCurrencies = currencies ?? [];
  return (
    <div className="space-y-3">
      <div>
        <label className="block text-xs text-text-muted mb-1">Валюта</label>
        {allCurrencies.length === 0 ? (
          // V13.2 — without currencies the form has no submit path
          // (the ``currency`` field is required server-side). Show
          // an explicit message rather than a row of empty pill
          // buttons that look like a broken Sheet.
          <div className="rounded-card border border-border bg-panel-2 px-3 py-2 text-xs text-text-muted">
            Валюты не загружены. Обновите страницу или проверьте раздел «Валюты».
          </div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {allCurrencies.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setCurrency(c.code)}
                className={`rounded-button px-3 py-1.5 text-sm transition ${
                  c.code === currency
                    ? "bg-accent text-accent-fg font-medium"
                    : "bg-panel-2 text-text-muted"
                }`}
              >
                {c.code}
              </button>
            ))}
          </div>
        )}
      </div>
      <div>
        <label className="block text-xs text-text-muted mb-1">
          Сумма (со знаком: + кредит, − дебет)
        </label>
        <Input
          inputMode="decimal"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="напр. -25.5"
        />
      </div>
      <div>
        <label className="block text-xs text-text-muted mb-1">
          Причина (необязательно)
        </label>
        <Input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="..."
        />
      </div>
      <div className="flex gap-2 pt-1">
        <Button
          type="button"
          variant="ghost"
          onClick={() => setAmount((v) => `-${Math.abs(Number(v || "0"))}`)}
          className="flex-1"
        >
          <Minus size={14} className="mr-1" /> Списать
        </Button>
        <Button
          type="button"
          variant="ghost"
          onClick={() => setAmount((v) => `${Math.abs(Number(v || "0"))}`)}
          className="flex-1"
        >
          <Plus size={14} className="mr-1" /> Зачислить
        </Button>
      </div>
      <Button
        type="button"
        disabled={adjust.isPending || !Number(amount)}
        onClick={async () => {
          try {
            await adjust.mutateAsync({
              currency_code: currency,
              amount: Number(amount),
              reason: reason.trim() || undefined,
            });
            toast.show({
              kind: "success",
              title: "Готово",
              body: `${currency} ${amount} применено`,
            });
            onClose();
          } catch (e) {
            toast.show({ kind: "error", title: "Ошибка", body: (e as Error).message });
          }
        }}
        className="w-full"
      >
        Применить
      </Button>
    </div>
  );
}
