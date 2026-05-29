import { useNavigate, useSearchParams } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import type { DealCreateWithTopupResponseDto } from "@/api/types";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { PinPromptModal } from "@/components/PinPromptModal";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { useToast } from "@/components/ui/Toast";
import { UserPicker } from "@/components/domain/UserPicker";
import {
  useCreateDealWithTopup,
  useCurrencies,
  useMe,
  usePublicSettings,
  useWalletBalances,
} from "@/api/hooks";
import { formatCurrency } from "@/lib/format";
import { haptic, openPaymentLink } from "@/lib/tg";
import { DealInvoiceModal } from "@/components/wallet/DealInvoiceModal";

// Item 18 — backend can return a structured ``insufficient_funds``
// payload on the create-deal 400. The ky ``beforeError`` hook
// JSON-stringifies that payload into ``err.message`` so we re-parse
// it here to render an inline "не хватает X" hint.
interface InsufficientFundsDetail {
  code: "insufficient_funds";
  message: string;
  required: string;
  balance: string;
  deficit: string;
  currency_code: string | null;
}

function parseInsufficientFunds(err: unknown): InsufficientFundsDetail | null {
  const raw = (err as Error | undefined)?.message;
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<InsufficientFundsDetail>;
    if (parsed && parsed.code === "insufficient_funds") {
      return parsed as InsufficientFundsDetail;
    }
  } catch {
    /* not JSON — fall through to generic error path */
  }
  return null;
}

function InvoiceRow({
  label,
  value,
  currency,
  strong = false,
}: {
  label: string;
  value: string | number;
  currency: string;
  strong?: boolean;
}) {
  return (
    <div className={"flex items-center justify-between " + (strong ? "font-semibold" : "")}>
      <span>{label}</span>
      <span>{value} {currency}</span>
    </div>
  );
}

export default function CreateDealPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const create = useCreateDealWithTopup();
  const toast = useToast();
  const { data: currencies } = useCurrencies({ kind: "fiat" });
  // Bug-11a — surface the buyer's fiat balances so we can (a) default
  // the picker to whichever currency already has funds and (b) show
  // the "На балансе: X" hint under the amount input.
  const { data: balances } = useWalletBalances({ kind: "fiat" });
  const { data: me } = useMe();
  // Bug-11d — commission preview needs the admin-tunable percentage.
  // ``usePublicSettings`` falls back to ``undefined`` while loading;
  // we mirror the backend default (5%) so the very first paint still
  // shows a sane "Итого" line instead of a flash of nothing.
  const { data: publicSettings } = usePublicSettings();
  const [counterparty, setCounterparty] = useState(params.get("to") ?? "");
  // Audit C1 — deals can only be initiated by the buyer (the side
  // whose balance gets locked into escrow). The "I'm the seller" tab
  // was removed because it let the caller freeze a victim's balance
  // for days. The role is fixed at ``buyer`` here and on the backend.
  const [sum, setSum] = useState("");
  const [description, setDescription] = useState("");
  // Bug-11a — default ``USD`` is overridden in the effect below once
  // ``useWalletBalances`` lands; we pick the first currency that has
  // a non-zero balance so the user doesn't have to retap the dropdown.
  const [currencyCode, setCurrencyCode] = useState("USD");
  const [currencyDefaulted, setCurrencyDefaulted] = useState(false);
  // V13 — buyer's preferred upstream invoice provider, persisted
  // on the deal row (``Deal.payment_provider``). Defaults to
  // ``"cryptobot"`` to match the wallet deposit flow.
  const [paymentProvider, setPaymentProvider] = useState<
    "cryptobot" | "crystalpay"
  >("cryptobot");
  const [pinOpen, setPinOpen] = useState(false);
  const [insufficient, setInsufficient] = useState<InsufficientFundsDetail | null>(null);
  const [created, setCreated] = useState<DealCreateWithTopupResponseDto | null>(null);
  const [invoiceModalOpen, setInvoiceModalOpen] = useState(false);

  // Per the deposit-flow plan, deals are funded from the buyer's
  // fiat balance — the dropdown therefore surfaces only fiat
  // currencies (UAH/RUB/USD). Crypto rows stay in the DB for the
  // historical ledger but are hidden from the create-deal picker.
  const currencyOptions = useMemo(
    () =>
      (currencies ?? [])
        .filter((c) => (c.kind ?? "crypto") === "fiat")
        .map((c) => ({
          value: c.code,
          label: `${c.code} — ${c.name}`,
        })),
    [currencies],
  );

  // Bug-11a — first-paint default: pick whichever fiat balance is
  // already funded. Skip on subsequent renders so a deliberate user
  // change to the dropdown is sticky.
  useEffect(() => {
    if (currencyDefaulted || !balances || balances.length === 0) return;
    const funded = balances.find((b) => b.amount > 0);
    if (funded) {
      setCurrencyCode(funded.currency.code);
    }
    setCurrencyDefaulted(true);
  }, [balances, currencyDefaulted]);

  // Bug-11a/d — derive the active balance row + commission percent
  // used to render the "На балансе" + "Итого" preview block. Both can
  // be ``undefined`` while data loads; the JSX below tolerates that.
  const activeBalance = useMemo(
    () => (balances ?? []).find((b) => b.currency.code === currencyCode),
    [balances, currencyCode],
  );
  const commissionPercent = useMemo(() => {
    if (!publicSettings) return 5;
    if (
      me?.is_vip === true &&
      publicSettings.vip_commission_percent >= 0
    ) {
      return publicSettings.vip_commission_percent;
    }
    return publicSettings.deal_commission_percent;
  }, [publicSettings, me]);
  const parsedAmount = useMemo(() => {
    const value = parseFloat(sum);
    return Number.isFinite(value) && value > 0 ? value : 0;
  }, [sum]);
  const decimals = activeBalance?.currency.decimals ?? 2;
  const commissionAmount = parsedAmount * (commissionPercent / 100);
  const totalFromBalance = parsedAmount + commissionAmount;
  const balanceCoversFull =
    !!activeBalance && activeBalance.amount >= totalFromBalance && parsedAmount > 0;

  function validate(): boolean {
    const amount = parseFloat(sum);
    if (!counterparty || !description || !Number.isFinite(amount) || amount <= 0) {
      haptic("error");
      return false;
    }
    return true;
  }

  async function submitDeal() {
    const amount = parseFloat(sum);
    setInsufficient(null);
    try {
      const deal = await create.mutateAsync({
        counterparty,
        role: "buyer",
        amount,
        description,
        currency_code: currencyCode,
        payment_provider: paymentProvider,
      });
      setCreated(deal);
      haptic("success");
      // Bug-11b/d — when the balance fully covers the deal the
      // backend returns ``topup.total == 0`` and routes the deal
      // straight to ``pending_confirmation``. The toast string
      // distinguishes the two outcomes so the user knows whether
      // they still need to pay an invoice.
      const total = parseFloat(String(deal.invoice.total));
      const paidFromBalance = Number.isFinite(total) && total <= 0;
      if (paidFromBalance) {
        toast.show({
          kind: "success",
          title: "Сделка создана — оплата с баланса",
        });
      } else {
        toast.show({ kind: "success", title: "Инвойс создан" });
        setInvoiceModalOpen(true);
      }
    } catch (e: unknown) {
      haptic("error");
      const lowFunds = parseInsufficientFunds(e);
      if (lowFunds) {
        setInsufficient(lowFunds);
        toast.show({
          kind: "error",
          title: `Не хватает ${lowFunds.deficit} ${lowFunds.currency_code ?? ""}`.trim(),
        });
        return;
      }
      toast.show({
        kind: "error",
        title: (e as Error)?.message || "Не удалось создать сделку",
      });
    } finally {
      // Bug-11c — the PIN modal already self-closes on
      // ``onSuccess`` before this function runs, but the create
      // mutation can throw *after* the close (network 400, low
      // funds, etc.). Resetting here guarantees the create button
      // re-enables and the user is not stuck on a faded form
      // waiting for a non-existent modal to dismiss.
      setPinOpen(false);
    }
  }

  function requestSubmit() {
    if (!validate()) return;
    // PIN re-prompt — sensitive money-moving action.
    setPinOpen(true);
  }

  return (
    <Page showBack>
      <Header title="Новая сделка" subtitle="Защита через гаранта" />
      <div className="px-4 space-y-3">
        <UserPicker
          label="Продавец (username)"
          placeholder="@username или ID"
          value={counterparty}
          onChange={setCounterparty}
        />
        {currencyOptions.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs text-text-muted px-1">Валюта</div>
            <Select
              value={currencyCode}
              options={currencyOptions}
              onChange={setCurrencyCode}
            />
          </div>
        )}
        <Input
          label={`Сумма (${currencyCode})`}
          type="number"
          min={0.01}
          step={0.01}
          value={sum}
          onChange={(e) => {
            setSum(e.target.value);
            if (insufficient) setInsufficient(null);
          }}
        />
        {activeBalance && (
          <div
            className="flex items-center justify-between text-xs text-text-muted -mt-1.5 px-1"
            data-testid="deal-balance-hint"
          >
            <span>
              На балансе:{" "}
              {formatCurrency(
                activeBalance.amount,
                activeBalance.currency.code,
                activeBalance.currency.decimals,
              )}
            </span>
            {activeBalance.amount > 0 && (
              <button
                type="button"
                className="text-accent underline"
                onClick={() => {
                  const maxDealAmount = Math.max(
                    0,
                    activeBalance.amount / (1 + commissionPercent / 100),
                  );
                  setSum(maxDealAmount.toFixed(decimals));
                }}
              >
                Макс
              </button>
            )}
          </div>
        )}
        {parsedAmount > 0 && activeBalance && (
          <div
            className="rounded-card border border-border bg-panel-2 px-3 py-2 text-[12px] leading-snug space-y-1"
            data-testid="deal-commission-preview"
          >
            <InvoiceRow
              label="Сумма сделки"
              value={parsedAmount.toFixed(decimals)}
              currency={activeBalance.currency.code}
            />
            <InvoiceRow
              label={`Комиссия (${commissionPercent % 1 ? commissionPercent.toFixed(1) : commissionPercent.toFixed(0)}%)`}
              value={commissionAmount.toFixed(decimals)}
              currency={activeBalance.currency.code}
            />
            <InvoiceRow
              label={balanceCoversFull ? "Итого с баланса" : "Итого"}
              value={totalFromBalance.toFixed(decimals)}
              currency={activeBalance.currency.code}
              strong
            />
            {balanceCoversFull ? (
              <div className="text-[11px] text-success">
                Будет списано с баланса, инвойс не потребуется.
              </div>
            ) : (
              <div className="text-[11px] text-text-muted">
                Недостающую сумму нужно будет оплатить инвойсом после создания.
              </div>
            )}
          </div>
        )}
        {!parsedAmount && (
          <div className="rounded-card border border-border bg-panel-2 px-3 py-2 text-[12px] text-text-muted leading-snug">
            После создания покупатель оплачивает единый инвойс: недостающая сумма
            для эскроу + комиссия платформы. Сделка активируется после оплаты.
          </div>
        )}
        {insufficient && (
          <div
            role="alert"
            className="rounded-card border border-danger/50 bg-danger/10 px-3 py-2 text-[12px] text-danger leading-snug"
          >
            <div className="font-semibold mb-0.5">Недостаточно средств</div>
            <div>
              Нужно: {insufficient.required} {insufficient.currency_code ?? ""}.
              На балансе: {insufficient.balance} {insufficient.currency_code ?? ""}.
              Не хватает {insufficient.deficit} {insufficient.currency_code ?? ""}.
            </div>
            <div className="mt-1">
              Уменьшите сумму или пополните баланс через инвойс сделки.
            </div>
          </div>
        )}
        <Textarea
          label="Описание сделки"
          placeholder="Что покупаете/продаёте, условия"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        {!balanceCoversFull && (
          <div>
            <div className="mb-1 text-[14px] font-medium">Платёжная система</div>
            <div
              className="grid grid-cols-2 gap-2"
              role="radiogroup"
              aria-label="Платёжная система"
            >
              {[
                { value: "cryptobot" as const, label: "CryptoBot" },
                { value: "crystalpay" as const, label: "Crystalpay" },
              ].map((opt) => {
                const selected = paymentProvider === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    data-testid={`provider-${opt.value}`}
                    onClick={() => setPaymentProvider(opt.value)}
                    className={
                      "rounded-button border px-4 py-2 text-sm font-medium transition " +
                      (selected
                        ? "border-accent bg-accent/10 text-accent"
                        : "border-border text-text-muted hover:text-text")
                    }
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </div>
        )}
        {created && (() => {
          // Bug-11b/d — when the balance covered everything the
          // backend returns ``topup_principal == 0`` and
          // ``total == 0``. Skip the invoice block and show a
          // "paid from balance" confirmation instead so the user
          // doesn't get sent to a zero-value pay-url.
          const totalNum = parseFloat(String(created.invoice.total));
          const paidFromBalance = Number.isFinite(totalNum) && totalNum <= 0;
          if (paidFromBalance) {
            return (
              <div
                className="rounded-card border border-success/40 bg-success/10 p-4 space-y-3"
                data-testid="deal-balance-paid"
              >
                <div>
                  <div className="text-sm font-semibold text-success">
                    Сделка #{created.deal.id} создана
                  </div>
                  <div className="text-xs text-text-muted">
                    Сумма и комиссия списаны с баланса. Сделка ждёт подтверждения продавцом.
                  </div>
                </div>
                <Button
                  type="button"
                  onClick={() => navigate(`/deals/${created.deal.id}`)}
                >
                  К сделке
                </Button>
              </div>
            );
          }
          // Topup required: when the realtime modal is closed, show a
          // compact "Оплатите инвойс #N" card that reopens it. The
          // modal itself handles polling, auto-open, and auto-navigate
          // — this card just gives the user a way back in.
          return (
            <div
              className="rounded-card border border-accent/40 bg-accent/10 p-4 space-y-3"
              data-testid="topup-invoice-preview"
            >
              <div>
                <div className="text-sm font-semibold text-accent">Инвойс #{created.deal.id} ждёт оплаты</div>
                <div className="text-xs text-text-muted">
                  Когда платёж пройдёт, сделка откроется автоматически.
                </div>
              </div>
              <div className="space-y-1 text-sm">
                <InvoiceRow label="Недостающая сумма" value={created.invoice.topup_principal} currency={created.invoice.currency_code} />
                <InvoiceRow label="Комиссия" value={created.invoice.commission} currency={created.invoice.currency_code} />
                <InvoiceRow label="Итого" value={created.invoice.total} currency={created.invoice.currency_code} strong />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Button
                  type="button"
                  onClick={() => setInvoiceModalOpen(true)}
                >
                  Открыть оплату
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => navigate(`/deals/${created.deal.id}`)}
                >
                  К сделке
                </Button>
              </div>
            </div>
          );
        })()}
        <Button fullWidth onClick={requestSubmit} disabled={create.isPending || created !== null}>
          {create.isPending
            ? "Создаю..."
            : created !== null
              ? "Сделка создана"
              : "Создать сделку"}
        </Button>
      </div>
      <PinPromptModal
        open={pinOpen}
        onClose={() => setPinOpen(false)}
        onSuccess={() => {
          setPinOpen(false);
          void submitDeal();
        }}
        title="Подтвердите PIN"
        subtitle="Введите PIN, чтобы создать сделку"
      />
      {created && invoiceModalOpen && created.invoice.pay_url && (
        <DealInvoiceModal
          open={invoiceModalOpen}
          onClose={() => setInvoiceModalOpen(false)}
          dealId={created.deal.id}
          depositId={created.invoice.deposit_id}
          payUrl={created.invoice.pay_url}
          amount={created.invoice.total}
          currencyCode={created.deal.currency_code ?? "USD"}
          provider={created.deal.payment_provider ?? "cryptobot"}
          canPay={true}
          successTitle="Сделка создана"
          successBody="Платёж прошёл. Сейчас откроем сделку."
          onSuccess={(dealId) => {
            setInvoiceModalOpen(false);
            setCreated(null);
            navigate(`/deals/${dealId}`, { replace: true });
          }}
        />
      )}
    </Page>
  );
}
