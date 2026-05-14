import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Search, Wallet, Plus, Minus } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Skeleton } from "@/components/ui/Skeleton";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { useToast } from "@/components/ui/Toast";
import {
  useAdminAdjustBalance,
  useAdminCurrencies,
  useAdminWallets,
} from "@/api/admin/hooks";
import { parseDecimal } from "@/lib/format";
import type { AdminWalletListItemDto } from "@/api/types";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";

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
  const { data, isLoading } = useAdminWallets({ q, page });
  const [target, setTarget] = useState<AdminWalletListItemDto | null>(null);

  const __guard = useAdminRedirect();
  if (!__guard.shouldRender) return null;

  return (
    <Page showBack onBack={() => navigate("/admin")}>
      <Header
        title="Балансы"
        subtitle={data ? `${data.total} пользователей` : undefined}
      />
      <div className="px-4 mb-3">
        <div className="flex items-center gap-2 bg-panel rounded-button px-3 py-2">
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
          data?.items.map((it, idx) => (
            <motion.button
              key={it.user_id}
              type="button"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.03 }}
              whileTap={{ scale: 0.98 }}
              onClick={() => setTarget(it)}
              className="w-full text-left bg-panel rounded-card p-3 hover:bg-panel-2 transition"
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
              <div className="mt-3 grid grid-cols-2 gap-1.5">
                {it.balances
                  .filter((b) => parseDecimal(b.total) > 0)
                  .slice(0, 4)
                  .map((b) => {
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
            </motion.button>
          ))
        )}
      </div>

      <Sheet
        open={!!target}
        onClose={() => setTarget(null)}
        title={target ? `Корректировка: ${target.display_name}` : undefined}
      >
        {target && <AdjustForm target={target} onClose={() => setTarget(null)} />}
      </Sheet>
    </Page>
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
