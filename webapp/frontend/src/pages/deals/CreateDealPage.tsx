import { useNavigate, useSearchParams } from "react-router-dom";
import { useState } from "react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { ToggleTabs } from "@/components/ui/ToggleTabs";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { Button } from "@/components/ui/Button";
import { useCreateDeal } from "@/api/hooks";
import { haptic } from "@/lib/tg";

export default function CreateDealPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const create = useCreateDeal();
  const [counterparty, setCounterparty] = useState(params.get("to") ?? "");
  const [role, setRole] = useState<"buyer" | "seller">("buyer");
  const [sum, setSum] = useState("");
  const [description, setDescription] = useState("");
  const [comissionFrom, setComissionFrom] = useState<"buyer" | "seller">("buyer");

  const submit = async () => {
    const amount = parseFloat(sum);
    if (!counterparty || !description || !Number.isFinite(amount) || amount <= 0) {
      haptic("error");
      return;
    }
    try {
      const deal = await create.mutateAsync({
        counterparty,
        role,
        sum: amount,
        description,
        pay_comission: comissionFrom,
      });
      haptic("success");
      navigate(`/deals/${deal.id}`);
    } catch {
      haptic("error");
    }
  };

  return (
    <Page showBack>
      <Header title="Новая сделка" subtitle="Защита через гаранта" />
      <div className="px-4 space-y-3">
        <ToggleTabs
          value={role}
          options={[
            { value: "buyer", label: "Я покупатель" },
            { value: "seller", label: "Я продавец" },
          ]}
          onChange={setRole}
          layoutId="create-deal-role"
        />
        <Input
          label="Контрагент (username)"
          placeholder="username без @"
          value={counterparty}
          onChange={(e) => setCounterparty(e.target.value)}
        />
        <Input
          label="Сумма (USDT)"
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
          layoutId="create-deal-comm"
        />
        <Button fullWidth onClick={submit} disabled={create.isPending}>
          {create.isPending ? "Создаю..." : "Создать сделку"}
        </Button>
      </div>
    </Page>
  );
}
