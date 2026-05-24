import { useNavigate, useSearchParams } from "react-router-dom";
import { useMemo, useState } from "react";
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
import { useCreateDealWithTopup, useCurrencies } from "@/api/hooks";
import { haptic, openTelegramLink } from "@/lib/tg";

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
  const { data: currencies } = useCurrencies();
  const [counterparty, setCounterparty] = useState(params.get("to") ?? "");
  // Audit C1 — deals can only be initiated by the buyer (the side
  // whose balance gets locked into escrow). The "I'm the seller" tab
  // was removed because it let the caller freeze a victim's balance
  // for days. The role is fixed at ``buyer`` here and on the backend.
  const [sum, setSum] = useState("");
  const [description, setDescription] = useState("");
  const [currencyCode, setCurrencyCode] = useState("USD");
  // V13 — buyer's preferred upstream invoice provider, persisted
  // on the deal row (``Deal.payment_provider``). Defaults to
  // ``"cryptobot"`` to match the wallet deposit flow.
  const [paymentProvider, setPaymentProvider] = useState<
    "cryptobot" | "crystalpay"
  >("cryptobot");
  const [pinOpen, setPinOpen] = useState(false);
  const [insufficient, setInsufficient] = useState<InsufficientFundsDetail | null>(null);
  const [created, setCreated] = useState<DealCreateWithTopupResponseDto | null>(null);

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
      toast.show({ kind: "success", title: "Инвойс создан" });
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
        <div className="rounded-card border border-border bg-panel-2 px-3 py-2 text-[12px] text-text-muted leading-snug">
          После создания покупатель оплачивает единый инвойс: недостающая сумма
          для эскроу + комиссия платформы. Сделка активируется после оплаты.
        </div>
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
        {created && (
          <div
            className="rounded-card border border-accent/40 bg-accent/10 p-4 space-y-3"
            data-testid="topup-invoice-preview"
          >
            <div>
              <div className="text-sm font-semibold text-accent">Инвойс на оплату</div>
              <div className="text-xs text-text-muted">
                Оплатите инвойс, чтобы сделка #{created.deal.id} перешла на подтверждение продавцом.
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
                onClick={() => openTelegramLink(created.invoice.pay_url)}
              >
                Открыть инвойс
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
        )}
        <Button fullWidth onClick={requestSubmit} disabled={create.isPending}>
          {create.isPending ? "Создаю..." : "Создать сделку"}
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
    </Page>
  );
}
