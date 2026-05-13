import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Vault, ShieldCheck } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Skeleton } from "@/components/ui/Skeleton";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { useToast } from "@/components/ui/Toast";
import {
  useAdminTreasury,
  useAdminTreasuryWithdraw,
  useAdminTreasuryWithdrawals,
} from "@/api/admin/hooks";
import { useMe } from "@/api/hooks";

/**
 * `/admin/treasury` — global commission accumulator + external payout.
 *
 * Balances are computed live (sum of ``commission_amount`` on completed
 * deals minus ``treasury_withdrawals`` per currency), so they're always
 * in sync with reality. External withdrawal requires 2FA (TOTP code) +
 * an explicit confirm checkbox.
 */
export default function AdminTreasuryPage() {
  const navigate = useNavigate();
  const { data: me } = useMe();
  const { data, isLoading } = useAdminTreasury();
  const { data: history } = useAdminTreasuryWithdrawals();
  const [sheetOpen, setSheetOpen] = useState(false);

  if (me && !me.is_admin) {
    navigate("/search", { replace: true });
    return null;
  }

  return (
    <Page showBack onBack={() => navigate("/admin")}>
      <Header
        title="Treasury"
        subtitle="Аккумулированная комиссия"
        right={
          <button
            type="button"
            onClick={() => setSheetOpen(true)}
            className="rounded-button bg-accent text-accent-fg px-3 py-1.5 text-sm font-medium active:scale-95"
          >
            Вывод
          </button>
        }
      />
      <div className="px-4 grid grid-cols-1 sm:grid-cols-2 gap-2 mb-4">
        {isLoading
          ? Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-card" />
            ))
          : data?.balances.map((b, idx) => (
              <motion.div
                key={b.currency_id}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.03 }}
                className="bg-panel rounded-card p-3"
              >
                <div className="flex items-center gap-2 mb-1">
                  <Vault size={14} className="text-text-muted" />
                  <span className="text-xs text-text-muted">{b.currency_code}</span>
                </div>
                <div className="text-lg font-bold">
                  {b.available.toFixed(b.decimals)}
                </div>
                <div className="text-[11px] text-text-muted">
                  Накоплено: {b.accrued.toFixed(b.decimals)} · Выведено:{" "}
                  {b.withdrawn.toFixed(b.decimals)}
                </div>
              </motion.div>
            ))}
      </div>
      <div className="px-4">
        <div className="text-xs text-text-muted mb-2">История выводов</div>
        {!history || history.length === 0 ? (
          <p className="text-sm text-text-muted text-center py-8">Выводов нет</p>
        ) : (
          <div className="space-y-2 pb-24">
            {history.map((h, idx) => (
              <motion.div
                key={h.id}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.03 }}
                className="bg-panel rounded-card p-3"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="font-medium">
                      {h.amount.toFixed(8)} {h.currency_code}
                    </div>
                    <div className="text-xs text-text-muted truncate">
                      → {h.address}
                    </div>
                    <div className="text-[11px] text-text-muted">
                      {new Date(h.created_at).toLocaleString()}
                    </div>
                  </div>
                  <span className="text-[10px] uppercase font-semibold text-success">
                    {h.status}
                  </span>
                </div>
                {h.cryptobot_transfer_id && (
                  <div className="text-[10px] text-text-muted mt-1 font-mono">
                    CB id: {h.cryptobot_transfer_id}
                  </div>
                )}
              </motion.div>
            ))}
          </div>
        )}
      </div>

      <Sheet open={sheetOpen} onClose={() => setSheetOpen(false)} title="Вывод комиссии">
        <WithdrawForm onClose={() => setSheetOpen(false)} />
      </Sheet>
    </Page>
  );
}

function WithdrawForm({ onClose }: { onClose: () => void }) {
  const { data } = useAdminTreasury();
  const [currency, setCurrency] = useState("USDT");
  const [amount, setAmount] = useState("");
  const [address, setAddress] = useState("");
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [totp, setTotp] = useState("");
  const withdraw = useAdminTreasuryWithdraw();
  const toast = useToast();
  return (
    <div className="space-y-3">
      <div>
        <label className="block text-xs text-text-muted mb-1">Валюта</label>
        <div className="flex flex-wrap gap-1.5">
          {data?.balances.map((b) => (
            <button
              key={b.currency_id}
              type="button"
              onClick={() => setCurrency(b.currency_code)}
              className={`rounded-button px-3 py-1.5 text-sm transition ${
                b.currency_code === currency
                  ? "bg-accent text-accent-fg font-medium"
                  : "bg-panel-2 text-text-muted"
              }`}
            >
              {b.currency_code} · {b.available.toFixed(b.decimals)}
            </button>
          ))}
        </div>
      </div>
      <div>
        <label className="block text-xs text-text-muted mb-1">Сумма</label>
        <Input
          inputMode="decimal"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
      </div>
      <div>
        <label className="block text-xs text-text-muted mb-1">Адрес / получатель</label>
        <Input value={address} onChange={(e) => setAddress(e.target.value)} />
      </div>
      <div>
        <label className="block text-xs text-text-muted mb-1">Комментарий</label>
        <Input value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      <label className="flex items-center gap-2 text-sm bg-panel-2 rounded-button px-3 py-2">
        <input
          type="checkbox"
          checked={confirm}
          onChange={(e) => setConfirm(e.target.checked)}
        />
        <span>
          Подтверждаю: вывожу {amount || "0"} {currency} на адрес выше
        </span>
      </label>
      <div>
        <label className="block text-xs text-text-muted mb-1 flex items-center gap-1">
          <ShieldCheck size={12} /> Код 2FA (TOTP)
        </label>
        <Input
          inputMode="numeric"
          value={totp}
          onChange={(e) => setTotp(e.target.value)}
          placeholder="6 цифр из аутентификатора"
        />
      </div>
      <Button
        type="button"
        disabled={withdraw.isPending || !confirm || !Number(amount) || !address || !totp}
        onClick={async () => {
          try {
            await withdraw.mutateAsync({
              body: {
                currency_code: currency,
                amount: Number(amount),
                address: address.trim(),
                confirm: true,
                note: note.trim() || undefined,
              },
              totpCode: totp,
            });
            toast.show({
              kind: "success",
              title: "Вывод инициирован",
              body: `${currency} ${amount}`,
            });
            onClose();
          } catch (e) {
            toast.show({ kind: "error", title: "Ошибка", body: (e as Error).message });
          }
        }}
        className="w-full"
      >
        Вывести
      </Button>
    </div>
  );
}
