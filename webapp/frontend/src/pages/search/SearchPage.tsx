import { useNavigate } from "react-router-dom";
import { useState } from "react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { SearchInput } from "@/components/ui/SearchInput";
import { ToggleTabs } from "@/components/ui/ToggleTabs";
import { Select } from "@/components/ui/Select";
import { EmptyState } from "@/components/ui/EmptyState";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { UserCard } from "@/components/domain/UserCard";
import { DesignationsHelp } from "@/components/domain/DesignationsHelp";
import { useUI } from "@/stores/ui";
import { useUsers } from "@/api/hooks";
import { Search as SearchIcon } from "lucide-react";

const FILTER_OPTIONS = [
  { value: "all", label: "Все" },
  { value: "arbiters", label: "Арбитры" },
  { value: "with_deposit", label: "С депозитом" },
  { value: "top_rating", label: "Топ рейтинг" },
];

export default function SearchPage() {
  const navigate = useNavigate();
  const mode = useUI((s) => s.searchMode);
  const setMode = useUI((s) => s.setSearchMode);

  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const { data: users, isLoading } = useUsers({ q, filter });

  return (
    <Page>
      <Header title="Поиск" subtitle="Найдите гаранта, услугу или арбитра" />
      <div className="px-4 space-y-3">
        <ToggleTabs
          value={mode}
          options={[
            { value: "users", label: "Пользователи" },
            { value: "services", label: "Услуги" },
          ]}
          onChange={(v) => {
            setMode(v);
            if (v === "services") navigate("/search/categories");
          }}
        />

        {mode === "users" && (
          <>
            <SearchInput
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Поиск пользователей"
            />
            <Select value={filter} options={FILTER_OPTIONS} onChange={setFilter} />
            <DesignationsHelp />

            {isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-[78px]" />
                ))}
              </div>
            ) : !users || users.length === 0 ? (
              <EmptyState
                icon={<SearchIcon className="size-6" />}
                title="Никого не найдено"
                description="Попробуйте другой запрос или фильтр"
              />
            ) : (
              <ul className="space-y-2">
                {users.map((u, i) => (
                  <li key={u.id}>
                    <UserCard user={u} index={i} />
                  </li>
                ))}
              </ul>
            )}
          </>
        )}

        {mode === "services" && (
          <div className="bg-panel border border-border rounded-card p-4 text-center">
            <div className="text-text-muted">Сначала выберите раздел</div>
            <Button size="sm" className="mt-3" onClick={() => navigate("/search/categories")}>
              Открыть категории
            </Button>
          </div>
        )}
      </div>
    </Page>
  );
}
