import { useNavigate } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { SearchInput } from "@/components/ui/SearchInput";
import { ToggleTabs } from "@/components/ui/ToggleTabs";
import { Select } from "@/components/ui/Select";
import { EmptyState } from "@/components/ui/EmptyState";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { Avatar } from "@/components/ui/Avatar";
import { BadgePrefix } from "@/components/ui/BadgePrefix";
import { OnlineDot } from "@/components/ui/OnlineDot";
import { DesignationsHelp } from "@/components/domain/DesignationsHelp";
import {
  SearchFilterSheet,
  type SearchFilters,
} from "@/components/domain/SearchFilterSheet";
import { ActiveFilterChips } from "@/components/domain/ActiveFilterChips";
import { useUI } from "@/stores/ui";
import { buildUsersSearchParams, useMe, useUsers, type UsersQueryParams } from "@/api/hooks";
import { api } from "@/api/client";
import { staggerDelay } from "@/lib/animate";
import { dealsLabel, formatMoney } from "@/lib/format";
import { countryFromCode } from "@/lib/countries";
import { cn } from "@/lib/cn";
import type { UserCardDto } from "@/api/types";
import { Search as SearchIcon, SlidersHorizontal, Star } from "lucide-react";
import { MOCK_USERS } from "./mockData";
import { SearchGateOverlay } from "./SearchGateOverlay";

type UserSearchFilter = NonNullable<UsersQueryParams["filter"]>;

const FILTER_OPTIONS = [
  { value: "all", label: "Все" },
  { value: "arbiters", label: "Арбитры" },
  { value: "with_deposit", label: "С депозитом" },
  { value: "top_rating", label: "Топ рейтинг" },
] satisfies Array<{ value: UserSearchFilter; label: string }>;

const USER_SEARCH_PAGE_SIZE = 50;

export default function SearchPage() {
  const navigate = useNavigate();
  const mode = useUI((s) => s.searchMode);
  const setMode = useUI((s) => s.setSearchMode);

  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<UserSearchFilter>("all");
  const [filters, setFilters] = useState<SearchFilters>({});
  const [sheetOpen, setSheetOpen] = useState(false);
  const [users, setUsers] = useState<UserCardDto[]>([]);
  const [reachedEnd, setReachedEnd] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);

  // Live-search debounce: avoid hitting ``/api/users?q=…`` on every
  // keystroke. 250 ms mirrors :class:`UserPicker` which the plan
  // uses as the visual reference for this dropdown UX.
  const [debouncedQ, setDebouncedQ] = useState("");
  useEffect(() => {
    const id = setTimeout(() => setDebouncedQ(q.trim()), 250);
    return () => clearTimeout(id);
  }, [q]);

  const queryParams = useMemo(
    () => ({
      q: debouncedQ,
      filter,
      rating: filters.rating,
      deals: filters.deals,
      status: filters.status,
      reg_from: filters.reg_from,
      reg_to: filters.reg_to,
    }),
    [debouncedQ, filter, filters],
  );
  const { data: me, isLoading: meLoading } = useMe();
  const isGated = me !== undefined && me.deals_count === 0 && !me.is_admin;
  const firstPageParams = useMemo(
    () => ({ ...queryParams, limit: USER_SEARCH_PAGE_SIZE, offset: 0 }),
    [queryParams],
  );
  const { data: usersPage, isLoading } = useUsers(firstPageParams, {
    enabled: me !== undefined && !isGated,
  });

  useEffect(() => {
    const page = usersPage ?? [];
    setUsers(page);
    setReachedEnd(page.length < USER_SEARCH_PAGE_SIZE);
    setLoadMoreError(null);
  }, [usersPage]);

  const loadMoreUsers = async () => {
    if (loadingMore || reachedEnd) return;
    setLoadingMore(true);
    setLoadMoreError(null);
    try {
      const page = await api
        .get("api/users", {
          searchParams: buildUsersSearchParams({
            ...queryParams,
            limit: USER_SEARCH_PAGE_SIZE,
            offset: users.length,
          }),
        })
        .json<UserCardDto[]>();
      setUsers((prev) => [...prev, ...page]);
      if (page.length < USER_SEARCH_PAGE_SIZE) {
        setReachedEnd(true);
      }
    } catch (e: unknown) {
      setLoadMoreError((e as Error)?.message || "Не удалось загрузить еще пользователей");
    } finally {
      setLoadingMore(false);
    }
  };

  const showSkeleton = meLoading || (!me && !isGated) || isLoading;

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

            {showSkeleton ? (
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-[78px]" />
                ))}
              </div>
            ) : isGated ? (
              <div className="relative overflow-hidden rounded-card">
                <div
                  role="listbox"
                  aria-label="Результаты поиска пользователей"
                  className={cn(
                    "bg-panel border border-border shadow-pop overflow-hidden",
                    "filter blur-[6px] select-none pointer-events-none",
                  )}
                >
                  <ul className="py-1.5">
                    {MOCK_USERS.map((u, i) => (
                      <SearchUserRow
                        key={u.id}
                        user={u}
                        index={i}
                        onPick={() => {}}
                      />
                    ))}
                  </ul>
                </div>
                <SearchGateOverlay message="В целях безопасности и защиты от спама детальный поиск пользователей доступен только участникам, совершившим хотя бы 1 сделку." />
              </div>
            ) : users.length === 0 ? (
              <EmptyState
                icon={<SearchIcon className="size-6" />}
                title="Никого не найдено"
                description="Попробуйте другой запрос или фильтр"
              />
            ) : (
              <>
                <div
                  role="listbox"
                  aria-label="Результаты поиска пользователей"
                  className={cn(
                    "rounded-card bg-panel border border-border shadow-pop overflow-hidden",
                    "animate-fade-in-down",
                  )}
                >
                  <ul className="py-1.5">
                    {users.map((u, i) => (
                      <SearchUserRow
                        key={u.id}
                        user={u}
                        index={i}
                        onPick={() => navigate(`/users/${u.username}`)}
                      />
                    ))}
                  </ul>
                </div>
                {!reachedEnd && users.length >= USER_SEARCH_PAGE_SIZE && (
                  <Button onClick={loadMoreUsers} disabled={loadingMore} className="w-full">
                    {loadingMore ? "Загружаю..." : "Показать еще"}
                  </Button>
                )}
                {loadMoreError && <div className="text-xs text-danger text-center">{loadMoreError}</div>}
              </>
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

/**
 * Dropdown-style row for the live user search.
 *
 * Mirrors :class:`UserPicker`'s row layout (avatar + name + meta on
 * the right) so the two surfaces feel like the same component
 * specialised for different callers. ``role="option"`` lets screen
 * readers announce the row as part of the parent listbox.
 */
function SearchUserRow({
  user,
  index,
  onPick,
}: {
  user: UserCardDto;
  index: number;
  onPick: () => void;
}) {
  const country = countryFromCode(user.country);
  const ratingLabel = user.reviews_count ? user.rating.toFixed(1) : "0.0";
  return (
    <li
      style={staggerDelay(index, 35, 280)}
      className="animate-fade-in-down"
    >
      <button
        type="button"
        role="option"
        aria-selected={false}
        onClick={onPick}
        data-testid={`search-user-${user.username}`}
        className={cn(
          "w-full flex items-center gap-3 px-3 py-2 text-left",
          "hover:bg-secondary/60 active:bg-secondary transition-colors",
        )}
      >
        <div className="relative shrink-0">
          <Avatar name={user.username} src={user.photo_url} size={44} />
          <span className="absolute -bottom-0.5 -right-0.5 ring-2 ring-panel rounded-full">
            <OnlineDot online={user.online} />
          </span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <BadgePrefix prefix={user.prefix} />
            <span className="font-medium text-[15px] truncate">
              {user.display_name?.trim() || user.username}
            </span>
            {country && (
              <span
                aria-label={country.name}
                title={country.name}
                className="shrink-0 text-sm leading-none"
              >
                {country.flag}
              </span>
            )}
          </div>
          <div className="text-[12px] text-text-muted truncate">
            @{user.username} · {dealsLabel(user.deals_count)}
          </div>
        </div>
        <div className="flex flex-col items-end shrink-0 gap-0.5">
          <span className="inline-flex items-center gap-1 text-accent text-sm font-semibold">
            <Star className="size-3.5" strokeWidth={2.5} />
            {ratingLabel}
          </span>
          <span className="text-accent text-xs font-semibold tabular-nums">
            {formatMoney(user.deposit)}
          </span>
        </div>
      </button>
    </li>
  );
}
