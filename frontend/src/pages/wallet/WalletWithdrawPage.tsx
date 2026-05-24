import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useSearchParams } from "react-router-dom";
import { ArrowUpFromLine, CreditCard, Wallet, X } from "lucide-react";
import {
  useAdmins,
  useCreateWalletWithdrawal,
  useWalletBalances,
} from "@/api/hooks";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { PinPromptModal } from "@/components/PinPromptModal";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { useToast } from "@/components/ui/Toast";
import { usePresence } from "@/lib/animate";
import { cn } from "@/lib/cn";
import { formatCurrency } from "@/lib/format";
import { haptic, openTelegramLink } from "@/lib/tg";

type WithdrawMethod = "crypto" | "card";

/**
 * Continental "Вывести депозит" page.
 *
 * Two withdrawal methods:
 *   * **Криптокошелёк** — drives ``POST /api/wallet/withdrawals``
 *     (the original on-chain flow). Only currencies with a non-zero
 *     balance are offered. Submitting the form re-prompts for the
 *     user's PIN before firing the mutation.
 *   * **Карта** — there is no automated card-payout integration yet;
 *     selecting this method opens an animated info dialog explaining
 *     the manual process and exposes a "Написать админу" button
 *     that deep-links to the first admin's Telegram chat.
 */
export default function WalletWithdrawPage() {
  // Item 15 — filter the source list to fiat balances; the
  // user-facing withdraw flow no longer offers crypto codes.
  const balances = useWalletBalances({ kind: "fiat" });
  const create = useCreateWalletWithdrawal();
  const toast = useToast();
  const { data: admins } = useAdmins();
  // Item 13 — ProfilePage's "Вывести" CTA can hint at a preferred
  // currency code via ``?currency=USD``; we honour it on first paint.
  const [searchParams] = useSearchParams();
  const initialCode = (searchParams.get("currency") ?? "").toUpperCase();

  const [method, setMethod] = useState<WithdrawMethod>("crypto");
  const [cardOpen, setCardOpen] = useState(false);
  const [pinOpen, setPinOpen] = useState(false);
  const [code, setCode] = useState<string>("");
  const [amount, setAmount] = useState<string>("");
  const [address, setAddress] = useState<string>("");

  const eligible = useMemo(
    () => (balances.data ?? []).filter((b) => b.amount > 0),
    [balances.data],
  );
  const current = useMemo(
    () => eligible.find((b) => b.currency.code === code),
    [eligible, code],
  );

  useEffect(() => {
    if (!code && eligible.length) {
      const fromUrl = initialCode
        ? eligible.find((b) => b.currency.code === initialCode)
        : undefined;
      setCode((fromUrl ?? eligible[0]).currency.code);
    }
  }, [code, eligible, initialCode]);

  if (balances.isLoading) {
    return (
      <Page showBack>
        <Header title="Вывести депозит" />
        <div className="px-4 space-y-2">
          <Skeleton className="h-12 w-full rounded-button" />
          <Skeleton className="h-12 w-full rounded-button" />
          <Skeleton className="h-11 w-full rounded-button" />
        </div>
      </Page>
    );
  }

  if (!eligible.length) {
    return (
      <Page showBack>
        <Header title="Вывести депозит" />
        <div className="px-4 space-y-3">
          <MethodSwitcher
            value={method}
            onChange={(m) => {
              setMethod(m);
              if (m === "card") setCardOpen(true);
            }}
          />
          <EmptyState
            title="У вас нет доступных для вывода валют"
            description="Пополните баланс через «Внести депозит», чтобы запросить вывод."
          />
        </div>
        <CardWithdrawModal
          open={cardOpen}
          onClose={() => {
            setCardOpen(false);
            setMethod("crypto");
          }}
          admins={admins ?? []}
        />
      </Page>
    );
  }

  // Audit M-7 — accept only a well-formed decimal literal so we
  // never need to call ``parseFloat`` (which would round-trip the
  // value through a 64-bit IEEE-754 double and silently truncate
  // the last few base-10 digits at the 10^10-ish scale USDT can
  // hit). The regex matches an optional leading digit run followed
  // by an optional fractional run, allowing at most 18 fractional
  // digits — comfortably above the 8 decimal places the DB column
  // stores so a normal balance string round-trips without rejection.
  // Strings like ``"1e5"`` / ``"0x10"`` / ``"NaN"`` are rejected.
  const _DECIMAL_RE = /^\d+(?:\.\d{1,18})?$|^\.\d{1,18}$/;

  function validate(): boolean {
    if (!current) return false;
    const trimmed = amount.trim();
    if (!_DECIMAL_RE.test(trimmed) || /^0+(?:\.0+)?$/.test(trimmed)) {
      haptic("error");
      toast.show({ kind: "error", title: "Введите корректную сумму" });
      return false;
    }
    if (!address.trim()) {
      haptic("error");
      toast.show({ kind: "error", title: "Введите адрес кошелька" });
      return false;
    }
    return true;
  }

  function requestSubmit() {
    if (!validate()) return;
    // PIN re-prompt — sensitive money-moving action.
    setPinOpen(true);
  }

  async function submitWithdraw() {
    if (!current) return;
    // Audit M-7 — send the decimal string as-is. The backend
    // ``WalletWithdrawCreateReq.amount: Decimal`` accepts a JSON
    // string and parses it without going through ``float``.
    const value = amount.trim();
    try {
      await create.mutateAsync({
        currency_code: current.currency.code,
        amount: value,
        address: address.trim(),
      });
      haptic("success");
      toast.show({
        kind: "success",
        title: "Заявка отправлена",
        body: "Администратор обработает её в ближайшее время.",
      });
      setAmount("");
      setAddress("");
    } catch (e: unknown) {
      haptic("error");
      toast.show({
        kind: "error",
        title: (e as Error)?.message || "Ошибка при выводе средств",
      });
    }
  }

  const options = eligible.map((b) => ({
    value: b.currency.code,
    label: `${b.currency.name} · ${formatCurrency(b.amount, b.currency.code, b.currency.decimals)}`,
  }));

  return (
    <Page showBack>
      <Header title="Вывести депозит" />
      <div className="px-4 space-y-3">
        <MethodSwitcher
          value={method}
          onChange={(m) => {
            setMethod(m);
            if (m === "card") setCardOpen(true);
          }}
        />
        <div>
          <div className="mb-1 text-[14px] font-medium">Выберите валюту для вывода средств</div>
          <Select
            value={code}
            options={options}
            onChange={(v) => {
              setCode(v);
              setAmount("");
            }}
            withIcon={false}
          />
        </div>
        {current && (
          <div className="flex items-center justify-between text-xs text-text-muted">
            <span>
              Доступно:{" "}
              {formatCurrency(
                current.amount,
                current.currency.code,
                current.currency.decimals,
              )}
            </span>
            <button
              type="button"
              className="text-accent underline"
              onClick={() => setAmount(current.amount_str)}
            >
              Всё
            </button>
          </div>
        )}
        <Input
          label="Сумма"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          type="number"
          inputMode="decimal"
          placeholder={current ? String(current.currency.min_withdraw) : "0"}
        />
        <Input
          label="Адрес кошелька"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder={current ? `Адрес ${current.currency.code}` : "Адрес"}
        />
        <Button
          fullWidth
          onClick={requestSubmit}
          disabled={create.isPending || !current}
        >
          <ArrowUpFromLine className="size-4" />
          {create.isPending ? "Создаю заявку..." : "Запросить вывод"}
        </Button>
        <p className="text-xs text-text-muted leading-relaxed">
          Средства заблокированы на время вывода. Через 72 часа свяжитесь с поддержкой,
          если статус не изменится.
        </p>
      </div>
      <PinPromptModal
        open={pinOpen}
        onClose={() => setPinOpen(false)}
        onSuccess={() => {
          setPinOpen(false);
          void submitWithdraw();
        }}
        title="Подтвердите PIN"
        subtitle="Введите PIN, чтобы запросить вывод"
      />
      <CardWithdrawModal
        open={cardOpen}
        onClose={() => {
          setCardOpen(false);
          setMethod("crypto");
        }}
        admins={admins ?? []}
      />
    </Page>
  );
}

interface MethodSwitcherProps {
  value: WithdrawMethod;
  onChange: (m: WithdrawMethod) => void;
}

function MethodSwitcher({ value, onChange }: MethodSwitcherProps) {
  return (
    <div>
      <div className="mb-1 text-[14px] font-medium">Способ вывода</div>
      <div className="grid grid-cols-2 gap-2">
        <MethodTile
          icon={<Wallet className="size-5" />}
          label="Криптокошелёк"
          active={value === "crypto"}
          onClick={() => onChange("crypto")}
        />
        <MethodTile
          icon={<CreditCard className="size-5" />}
          label="Карта"
          active={value === "card"}
          onClick={() => onChange("card")}
        />
      </div>
    </div>
  );
}

interface MethodTileProps {
  icon: React.ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
}

function MethodTile({ icon, label, active, onClick }: MethodTileProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "h-14 rounded-card border flex items-center justify-center gap-2.5 text-[14px] font-medium",
        "transition-all duration-200 active:scale-[0.98]",
        active
          ? "bg-accent/15 border-accent/60 text-text shadow-glow"
          : "bg-panel border-border text-text-muted hover:border-text-muted/40",
      )}
    >
      {icon}
      {label}
    </button>
  );
}

interface CardWithdrawModalProps {
  open: boolean;
  onClose: () => void;
  admins: { username: string }[];
}

function CardWithdrawModal({ open, onClose, admins }: CardWithdrawModalProps) {
  const { mounted, visible } = usePresence(open, 220);
  const adminUsername = admins[0]?.username;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  function writeAdmin() {
    if (!adminUsername) return;
    haptic("medium");
    openTelegramLink(`https://t.me/${adminUsername}`);
    onClose();
  }

  if (!mounted) return null;

  // V14-card — render via React portal so the modal is not subject
  // to the parent ``<Page>``'s ``animate-fadein`` transform creating
  // a fixed-position containing block (which made ``fixed inset-0``
  // align to the short Page div instead of the viewport and clipped
  // the dialog off the top of the screen on empty-balance views).
  const body = (
    <div role="dialog" aria-modal="true" aria-labelledby="card-withdraw-title">
      <div
        className={cn(
          "fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm transition-opacity duration-200",
          visible ? "opacity-100" : "opacity-0",
        )}
        onClick={onClose}
      />
      <div
        className={cn(
          "fixed inset-0 z-[61] grid place-items-center p-4 pointer-events-none",
          "transition-opacity duration-200",
          visible ? "opacity-100" : "opacity-0",
        )}
      >
        <div
          className={cn(
            "pointer-events-auto w-full max-w-sm rounded-3xl bg-panel border border-border shadow-pop p-6",
            "transform transition-all duration-200",
            visible ? "scale-100 opacity-100" : "scale-95 opacity-0",
          )}
        >
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3 min-w-0">
              <div className="size-11 grid place-items-center rounded-2xl bg-accent/15 text-accent shrink-0">
                <CreditCard className="size-5" />
              </div>
              <div className="min-w-0">
                <h2
                  id="card-withdraw-title"
                  className="text-[18px] font-semibold tracking-tight text-text"
                >
                  Вывод на карту
                </h2>
                <p className="text-[12px] text-text-muted">Ручная обработка администратором</p>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Закрыть"
              className="size-9 -mr-1 -mt-1 grid place-items-center rounded-full text-text-muted hover:bg-secondary active:scale-95 transition"
            >
              <X className="size-4" />
            </button>
          </div>
          <p className="mt-4 text-[14px] text-text-muted leading-relaxed">
            Автоматический вывод на банковскую карту пока недоступен.
            Чтобы вывести средства на карту, напишите администратору —
            он обработает заявку вручную.
          </p>
          <div className="mt-5 grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={onClose}
              className="h-11 rounded-button bg-secondary text-text font-medium hover:opacity-90 active:opacity-80 transition"
            >
              Отмена
            </button>
            <Button
              size="md"
              onClick={writeAdmin}
              disabled={!adminUsername}
              className="!h-11"
            >
              Написать админу
            </Button>
          </div>
          {!adminUsername && (
            <p className="mt-3 text-[12px] text-danger">
              Контакт администратора пока недоступен. Попробуйте позже.
            </p>
          )}
        </div>
      </div>
    </div>
  );

  if (typeof document === "undefined") return body;
  return createPortal(body, document.body);
}
