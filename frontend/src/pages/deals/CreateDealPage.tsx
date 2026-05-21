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
  const [currencyCode, setCurrencyCode] = useState("USDT");
  const [pinOpen, setPinOpen] = useState(false);

  const currencyOptions = useMemo(
    () =>
      (currencies ?? []).map((c) => ({
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
    try {
      const deal = await create.mutateAsync({
        counterparty,
        role: "buyer",
        amount,
        description,
        pay_comission: comissionFrom,
        currency_code: currencyCode,
      });
      haptic("success");
      navigate(`/deals/${deal.id}`);
    } catch (e: unknown) {
      haptic("error");
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
          onChange={(e) => setSum(e.target.value)}
        />
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
