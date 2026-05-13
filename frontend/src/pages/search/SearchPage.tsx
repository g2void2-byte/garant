import { useNavigate } from "react-router-dom";
import { useMemo, useState } from "react";
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
import {
  SearchFilterSheet,
  type SearchFilters,
} from "@/components/domain/SearchFilterSheet";
import { ActiveFilterChips } from "@/components/domain/ActiveFilterChips";
import { useUI } from "@/stores/ui";
import { useUsers } from "@/api/hooks";
import { Search as SearchIcon, SlidersHorizontal } from "lucide-react";

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
  const [filters, setFilters] = useState<SearchFilters>({});
  const [sheetOpen, setSheetOpen] = useState(false);

  const queryParams = useMemo(
    () => ({
      q,
      filter,
      rating: filters.rating,
      deals: filters.deals,
      deposit_min: filters.deposit_min,
      status: filters.status,
      reg_from: filters.reg_from,
      reg_to: filters.reg_to,
    }),
    [q, filter, filters],
  );
  const { data: users, isLoading } = useUsers(queryParams);

  const removeFilter = (key: keyof SearchFilters) => {
    setFilters((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  return (
    <Page>
      <Header title="Поиск" subtitle="Найдите нужного пользователя или услугу за секунды" />
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
            <div className="flex gap-2">
              <div className="flex-1 min-w-0">
                <Select value={filter} options={FILTER_OPTIONS} onChange={setFilter} />
              </div>
              <Button
                variant="secondary"
                size="md"
                onClick={() => setSheetOpen(true)}
                aria-label="Открыть фильтры"
              >
                <SlidersHorizontal className="size-4" />
                Фильтры
              </Button>
            </div>
            <ActiveFilterChips
              value={filters}
              onRemove={removeFilter}
              onClearAll={() => setFilters({})}
            />
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

      <SearchFilterSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        value={filters}
        onApply={setFilters}
      />
    </Page>
  );
}
