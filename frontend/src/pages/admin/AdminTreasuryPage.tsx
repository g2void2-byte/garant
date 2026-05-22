import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Vault, ShieldCheck } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { AdminHeader } from "@/components/layout/AdminHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { useToast } from "@/components/ui/Toast";
import {
  useAdminTreasury,
  useAdminTreasuryMarkSent,
  useAdminTreasuryWithdraw,
  useAdminTreasuryWithdrawals,
} from "@/api/admin/hooks";
import type { AdminTreasuryWithdrawDto } from "@/api/types";
import { parseDecimal } from "@/lib/format";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";

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
  const { data, isLoading } = useAdminTreasury();
  const { data: history } = useAdminTreasuryWithdrawals();
  const [sheetOpen, setSheetOpen] = useState(false);

  const __guard = useAdminRedirect();
  if (!__guard.shouldRender) return null;

  return (
    <Page showBack onBack={() => navigate("/admin")}>
      <AdminHeader
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
          : data?.balances.map((b, _idx) => (
              <div
                key={b.currency_id}
                className="bg-panel rounded-card p-3"
              >
                <div className="flex items-center gap-2 mb-1">
                  <Vault size={14} className="text-text-muted" />
                  <span className="text-xs text-text-muted">{b.currency_code}</span>
                </div>
                <div className="text-lg font-bold">
                  {parseDecimal(b.available).toFixed(b.decimals)}
                </div>
                <div className="text-[11px] text-text-muted">
                  Накоплено: {parseDecimal(b.accrued).toFixed(b.decimals)} · Выведено:{" "}
                  {parseDecimal(b.withdrawn).toFixed(b.decimals)}
                </div>
              </div>
            ))}
      </div>
      <div className="px-4">
        <div className="text-xs text-text-muted mb-2">История выводов</div>
        {!history || history.length === 0 ? (
          <p className="text-sm text-text-muted text-center py-8">Выводов нет</p>
        ) : (
          <div className="space-y-2 pb-24">
            {history.map((h, _idx) => (
              <WithdrawalRow key={h.id} h={h} />
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

function WithdrawalRow({ h }: { h: AdminTreasuryWithdrawDto }) {
  // Manual reconciliation entry point for stuck ``pending`` rows.
  // Visible only when the row is ``pending`` — the audit-followup PR
  // documents this as the Phase 2 → Phase 3 recovery path.
  const [markOpen, setMarkOpen] = useState(false);
  const statusColor =
    h.status === "sent"
      ? "text-success"
      : h.status === "failed"
        ? "text-danger"
        : "text-warning";
  return (
    <div className="bg-panel rounded-card p-3">
      <div className="flex items-start justify-between">
        <div>
          <div className="font-medium">
            {parseDecimal(h.amount).toFixed(8)} {h.currency_code}
          </div>
          <div className="text-xs text-text-muted truncate">→ {h.address}</div>
          <div className="text-[11px] text-text-muted">
            {new Date(h.created_at).toLocaleString()}
          </div>
        </div>
        <span
          className={`text-[10px] uppercase font-semibold ${statusColor}`}
        >
          {h.status}
        </span>
      </div>
      {h.cryptobot_transfer_id && (
        <div className="text-[10px] text-text-muted mt-1 font-mono">
          CB id: {h.cryptobot_transfer_id}
        </div>
      )}
      {h.status === "pending" && (
        <>
          <button
            type="button"
            onClick={() => setMarkOpen(true)}
            className="mt-2 rounded-button bg-panel-2 text-text-muted px-3 py-1 text-[11px] font-medium active:scale-95"
          >
            Отметить отправленным
          </button>
          <Sheet
            open={markOpen}
            onClose={() => setMarkOpen(false)}
            title="Ручная сверка"
          >
            <MarkSentForm row={h} onClose={() => setMarkOpen(false)} />
          </Sheet>
        </>
      )}
    </div>
  );
}

function MarkSentForm({
  row,
  onClose,
}: {
  row: AdminTreasuryWithdrawDto;
  onClose: () => void;
}) {
  const [transferId, setTransferId] = useState("");
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState(false);
  const markSent = useAdminTreasuryMarkSent();
  const toast = useToast();
  return (
    <div className="space-y-3">
      <div className="text-xs text-text-muted bg-panel-2 rounded-button px-3 py-2">
        Используй только после того, как вручную убедился, что CryptoBot уже
        провёл эту выплату (spend_id или dashboard). Новый transfer не
        инициируется.
      </div>
      <div className="text-sm">
        <span className="text-text-muted">Сумма:</span>{" "}
        <span className="font-medium">
          {parseDecimal(row.amount).toFixed(8)} {row.currency_code}
        </span>
      </div>
      <div className="text-sm">
        <span className="text-text-muted">Получатель:</span>{" "}
        <span className="font-mono">{row.address}</span>
      </div>
      <div>
        <label className="block text-xs text-text-muted mb-1">
          CryptoBot transfer_id (опционально)
        </label>
        <Input
          inputMode="numeric"
          pattern="[0-9]+"
          placeholder="напр., 12345678"
          value={transferId}
          onChange={(e) => setTransferId(e.target.value.replace(/\D+/g, ""))}
        />
      </div>
      <div>
        <label className="block text-xs text-text-muted mb-1">
          Комментарий (будет вписан в audit row)
        </label>
        <Input value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      <label className="flex items-center gap-2 text-sm bg-panel-2 rounded-button px-3 py-2">
        <input
          type="checkbox"
          checked={confirm}
          onChange={(e) => setConfirm(e.target.checked)}
        />
        <span>
          Подтверждаю: CryptoBot уже выплатил по этой заявке
        </span>
      </label>
      <div className="text-xs text-text-muted flex items-center gap-1 bg-panel-2 rounded-button px-3 py-2">
        <ShieldCheck size={12} />
        Код 2FA будет запрошен один раз в 24 часа во всплывающем окне.
      </div>
      <Button
        type="button"
        disabled={markSent.isPending || !confirm}
        onClick={async () => {
          try {
            await markSent.mutateAsync({
              id: row.id,
              body: {
                confirm: true,
                cryptobot_transfer_id: transferId.trim() || undefined,
                note: note.trim() || undefined,
              },
            });
            toast.show({
              kind: "success",
              title: "Сверка выполнена",
              body: `#${row.id} → sent`,
            });
            onClose();
          } catch (e) {
            toast.show({
              kind: "error",
              title: "Ошибка",
              body: (e as Error).message,
            });
          }
        }}
        className="w-full"
      >
        Подтвердить отправку
      </Button>
    </div>
  );
}

function WithdrawForm({ onClose }: { onClose: () => void }) {
  const { data } = useAdminTreasury();
  const [currency, setCurrency] = useState("USDT");
  const [amount, setAmount] = useState("");
  const [address, setAddress] = useState("");
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState(false);
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
              {b.currency_code} · {parseDecimal(b.available).toFixed(b.decimals)}
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
        <label className="block text-xs text-text-muted mb-1">
          Telegram user_id получателя
        </label>
        <Input
          inputMode="numeric"
          pattern="[0-9]+"
          placeholder="например, 50000001"
          value={address}
          onChange={(e) =>
            // Strip non-digits at the input layer so the backend
            // ``_address_ok`` validator never sees a "Txxx…" wallet
            // address. CryptoBot ``transfer`` only accepts a numeric
            // ``user_id`` — wallet addresses aren't supported, so the
            // input must be a Telegram user_id (digits).
            setAddress(e.target.value.replace(/\D+/g, ""))
          }
        />
        <p className="text-[11px] text-text-muted mt-1">
          CryptoBot принимает только Telegram user_id (число), а не wallet-адрес.
        </p>
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
      <div className="text-xs text-text-muted flex items-center gap-1 bg-panel-2 rounded-button px-3 py-2">
        <ShieldCheck size={12} />
        Код 2FA будет запрошен один раз в 24 часа во всплывающем окне.
      </div>
      <Button
        type="button"
        disabled={withdraw.isPending || !confirm || !Number(amount) || !address}
        onClick={async () => {
          try {
            await withdraw.mutateAsync({
              currency_code: currency,
              amount: Number(amount),
              address: address.trim(),
              confirm: true,
              note: note.trim() || undefined,
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
