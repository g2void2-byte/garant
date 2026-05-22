import { useNavigate, useSearchParams } from "react-router-dom";
import { useMemo, useState } from "react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { PinPromptModal } from "@/components/PinPromptModal";
import { ToggleTabs } from "@/components/ui/ToggleTabs";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { useToast } from "@/components/ui/Toast";
import { UserPicker } from "@/components/domain/UserPicker";
import { useCreateDeal, useCurrencies } from "@/api/hooks";
import { haptic } from "@/lib/tg";

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

export default function CreateDealPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const create = useCreateDeal();
  const toast = useToast();
  const { data: currencies } = useCurrencies();
  const [counterparty, setCounterparty] = useState(params.get("to") ?? "");
  // Audit C1 — deals can only be initiated by the buyer (the side
  // whose balance gets locked into escrow). The "I'm the seller" tab
  // was removed because it let the caller freeze a victim's balance
  // for days. The role is fixed at ``buyer`` here and on the backend.
  const [sum, setSum] = useState("");
  const [description, setDescription] = useState("");
  const [comissionFrom, setComissionFrom] = useState<"buyer" | "seller">(
    "buyer",
  );
  const [currencyCode, setCurrencyCode] = useState("USD");
  // V13 — buyer's preferred upstream invoice provider, persisted
  // on the deal row (``Deal.payment_provider``). Defaults to
  // ``"cryptobot"`` to match the wallet deposit flow.
  const [paymentProvider, setPaymentProvider] = useState<
    "cryptobot" | "crystalpay"
  >("cryptobot");
  const [pinOpen, setPinOpen] = useState(false);
  const [insufficient, setInsufficient] = useState<InsufficientFundsDetail | null>(null);

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
        pay_comission: comissionFrom,
        currency_code: currencyCode,
        payment_provider: paymentProvider,
      });
      haptic("success");
      navigate(`/deals/${deal.id}`);
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
        {/* Item 18 — make it explicit that the buyer-pays-commission
            mode locks more than the deal amount. Pre-fix the toggle
            label was the only hint and users hit "Недостаточно средств"
            with a balance exactly equal to the typed amount. */}
        {comissionFrom === "buyer" && (
          <div className="rounded-card border border-border bg-panel-2 px-3 py-2 text-[12px] text-text-muted leading-snug">
            Покупатель платит сумму + комиссию платформы (~5%, для VIP ниже).
            Убедитесь, что на балансе хватает на сумму вместе с комиссией.
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
              Уменьшите сумму или переключите комиссию на продавца.
            </div>
          </div>
        )}
        <Textarea
          label="Описание сделки"
          placeholder="Что покупаете/продаёте, условия"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <ToggleTabs
          value={comissionFrom}
          options={[
            { value: "buyer", label: "Комиссию платит покупатель" },
            { value: "seller", label: "Комиссию платит продавец" },
          ]}
          onChange={setComissionFrom}
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
