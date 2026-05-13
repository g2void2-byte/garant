import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { ToggleTabs } from "@/components/ui/ToggleTabs";
import { Select } from "@/components/ui/Select";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { DealRow } from "@/components/domain/DealRow";
import { Button } from "@/components/ui/Button";
import { useDeals } from "@/api/hooks";

const STATUS_OPTIONS = [
  { value: "", label: "Все статусы" },
  { value: "pending_confirmation", label: "Ожидает подтверждения" },
  { value: "in_progress", label: "В работе" },
  { value: "pending_cancellation", label: "Запрошена отмена" },
  { value: "arbitration", label: "Арбитраж" },
  { value: "completed", label: "Завершена" },
  { value: "resolved_for_buyer", label: "В пользу покупателя" },
  { value: "resolved_for_seller", label: "В пользу продавца" },
  { value: "cancelled", label: "Отменена" },
  { value: "cancelled_for_inactivity", label: "Отмена за неактивность" },
];

export default function DealsPage() {
  const navigate = useNavigate();
  const [role, setRole] = useState<"all" | "buyer" | "seller">("all");
  const [status, setStatus] = useState("");
  const { data, isLoading } = useDeals({ role, status: status || undefined });

  return (
    <Page>
      <Header
        title="Мои сделки"
        subtitle="История и активные сделки"
        right={
          <Button size="sm" onClick={() => navigate("/deals/new")}>
            <Plus className="size-4" /> Новая
          </Button>
        }
      />
      <div className="px-4 space-y-3">
        <ToggleTabs
          value={role}
          options={[
            { value: "all", label: "Все" },
            { value: "buyer", label: "Покупки" },
            { value: "seller", label: "Продажи" },
          ]}
          onChange={setRole}
        />
        <Select value={status} options={STATUS_OPTIONS} onChange={setStatus} />

        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
        ) : !data || data.length === 0 ? (
          <EmptyState title="Сделок пока нет" description="Нажмите «Новая», чтобы создать сделку" />
        ) : (
          <div className="space-y-2">
            {data.map((d, i) => (
              <DealRow key={d.id} deal={d} index={i} />
            ))}
          </div>
        )}
      </div>
    </Page>
  );
}
