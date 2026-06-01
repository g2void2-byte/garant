import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowDownToLine } from "lucide-react";
import {
  useCreateWalletDeposit,
  useCurrencies,
  useWalletBalances,
} from "@/api/hooks";
import { DepositStatusModal } from "@/components/wallet/DepositStatusModal";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { formatCurrency } from "@/lib/format";
import { haptic, openPaymentLink } from "@/lib/tg";
import type { WalletDepositDto } from "@/api/types";

type DepositProvider = "cryptobot" | "crystalpay";

const PROVIDER_OPTIONS: { value: DepositProvider; label: string }[] = [
  { value: "cryptobot", label: "CryptoBot" },
  { value: "crystalpay", label: "Crystalpay" },
];

const PROVIDER_LABELS: Record<DepositProvider, string> = {
  cryptobot: "CryptoBot",
  crystalpay: "Crystalpay",
};

const DECIMAL_RE = /^\d+(?:\.\d{1,18})?$|^\.\d{1,18}$/;

/**
 * Continental "Пополнение баланса" page.
 *
 * Continental layout:
 *   - Currency picker (dropdown showing all active currencies).
 *   - Amount input (with min-deposit placeholder).
 *   - "Пополнить баланс" button — opens the CryptoBot invoice URL.
 *   - Helper text below: "Пополните баланс через выбранную сеть и валюту".
 */
export default function WalletDepositPage() {
  // Item 15 — fetch only fiat options server-side; the in-page
  // ``filter(kind === 'fiat')`` below stays as a defensive guard so a
  // partial response from a stale cache doesn't surface crypto rows.
  const currencies = useCurrencies({ kind: "fiat" });
  const balances = useWalletBalances({ kind: "fiat" });
  const create = useCreateWalletDeposit();
  const toast = useToast();
  const navigate = useNavigate();
  // Item 13 — ProfilePage's "Пополнить" CTA navigates here with
  // ``?currency=USD``; honour the URL hint so the dropdown lands on
  // the user's preferred fiat code without a manual click.
  const [searchParams] = useSearchParams();
  const initialCode = (searchParams.get("currency") ?? "").toUpperCase();

  const [code, setCode] = useState<string>("");
  const [amount, setAmount] = useState<string>("");
  const [provider, setProvider] = useState<DepositProvider>("cryptobot");
  // Track the freshly-created deposit so ``DepositStatusModal`` can
  // poll its status, surface real-time updates from the WS push and
  // auto-open the upstream invoice URL after a brief animation in.
  const [activeDeposit, setActiveDeposit] = useState<WalletDepositDto | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const fiatCurrencies = useMemo(
    () => (currencies.data ?? []).filter((c) => (c.kind ?? "crypto") === "fiat"),
    [currencies.data],
  );
  const current = useMemo(
    () => fiatCurrencies.find((c) => c.code === code),
    [fiatCurrencies, code],
  );
  const balance = useMemo(
    () => balances.data?.find((b) => b.currency.code === code),
    [balances.data, code],
  );

  useEffect(() => {
    if (!code && fiatCurrencies.length) {
      // Order of preference: URL hint (``?currency=USD``) → USD seed →
      // first available fiat row. Keeps the dropdown deterministic
      // across reloads and survives a fiat catalogue trimmed on the
      // backend.
      const fromUrl = initialCode
        ? fiatCurrencies.find((c) => c.code === initialCode)
        : undefined;
      const usd = fiatCurrencies.find((c) => c.code === "USD");
      setCode((fromUrl ?? usd ?? fiatCurrencies[0]).code);
    }
  }, [code, fiatCurrencies, initialCode]);

  useEffect(() => {
    if (current && !amount) {
      setAmount(String(current.min_deposit));
    }
  }, [current, amount]);

  if (currencies.isLoading) {
    return (
      <Page showBack>
        <Header title="Пополнение баланса" />
        <div className="px-4 space-y-2">
          <Skeleton className="h-12 w-full rounded-button" />
          <Skeleton className="h-12 w-full rounded-button" />
          <Skeleton className="h-11 w-full rounded-button" />
        </div>
      </Page>
    );
  }

  async function submit() {
    if (!current) return;
    const value = amount.trim();
    if (!DECIMAL_RE.test(value) || /^0+(?:\.0+)?$/.test(value)) {
      haptic("error");
      toast.show({ kind: "error", title: "Введите корректную сумму" });
      return;
    }
    try {
      const dep = await create.mutateAsync({
        currency_code: current.code,
        amount: value,
        provider,
      });
      haptic("success");
      setActiveDeposit(dep);
      setModalOpen(true);
      toast.show({
        kind: "success",
        title: "Счёт создан",
        body: `Оплатите ${formatCurrency(dep.amount, dep.currency.code, current.decimals)} в ${PROVIDER_LABELS[provider]}.`,
      });
      if (dep.pay_url) openPaymentLink(dep.pay_url);
    } catch (e: unknown) {
      haptic("error");
      toast.show({
        kind: "error",
        title: (e as Error)?.message || "Не удалось создать счет на оплату",
      });
    }
  }

  const currencyOptions = fiatCurrencies.map((c) => ({
    value: c.code,
    // Fiat rows have no ``network`` (it's a crypto concept); render
    // the code alongside the name so the dropdown reads e.g.
    // "Українська гривня · UAH" rather than the awkward
    // "Українська гривня ()".
    label: `${c.name} · ${c.code}`,
  }));

  return (
    <Page showBack>
      <Header title="Пополнение баланса" />
      <div className="px-4 space-y-3">
        <div>
          <div className="mb-1 text-[14px] font-medium">Платёжная система</div>
          <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Платёжная система">
            {PROVIDER_OPTIONS.map((opt) => {
              const selected = provider === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  data-testid={`provider-${opt.value}`}
                  onClick={() => setProvider(opt.value)}
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
        <div>
          <div className="mb-1 text-[14px] font-medium">Выберите валюту</div>
          <Select
            value={code}
            options={currencyOptions}
            onChange={setCode}
            withIcon={false}
            placeholder="Выберите валюту"
          />
        </div>
        <Input
          label="Сумма"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          type="number"
          inputMode="decimal"
          placeholder={current ? String(current.min_deposit) : "0"}
        />
        {current && (
          <div className="text-xs text-text-muted">
            Минимум: {formatCurrency(current.min_deposit, current.code, current.decimals)}
            {(balance?.amount ?? 0) > 0 && (
              <>
                {" "}
                · Доступно:{" "}
                {formatCurrency(balance!.amount, current.code, current.decimals)}
              </>
            )}
          </div>
        )}
        <Button
          fullWidth
          onClick={submit}
          disabled={create.isPending || !current}
        >
          <ArrowDownToLine className="size-4" />
          {create.isPending ? "Создаю счет..." : "Пополнить баланс"}
        </Button>
        <p className="text-xs text-text-muted leading-relaxed">
          Пополните баланс через выбранную сеть и валюту. Уведомления о пополнениях
          приходят автоматически.
        </p>
      </div>
      <DepositStatusModal
        deposit={activeDeposit}
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSuccess={() => {
          setModalOpen(false);
          navigate("/profile");
        }}
      />
    </Page>
  );
}
