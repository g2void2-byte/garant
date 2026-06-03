import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Search, Filter, ChevronLeft, ChevronRight } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { AdminHeader } from "@/components/layout/AdminHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { BadgePrefix } from "@/components/ui/BadgePrefix";
import { useAdminUsers } from "@/api/admin/hooks";
import type {
  AdminListUsersQuery,
  AdminUserListItemDto,
  AdminUserRoleFilter,
  AdminUserStatusFilter,
} from "@/api/types";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";
import { parsePositiveIntRouteParam } from "@/lib/routeParams";

// Audit L-10 — ``null`` is the in-component sentinel for "no filter"
// (replaces the string ``"any"``); the value sent to the API is
// ``undefined`` so the URL param is omitted entirely.
const ROLES: Array<{ value: AdminUserRoleFilter | null; label: string }> = [
  { value: null, label: "Все" },
  { value: "admin", label: "Админы" },
  { value: "arbiter", label: "Арбитры" },
  { value: "vip", label: "VIP" },
  { value: "regular", label: "Обычные" },
];

const STATUSES: Array<{ value: AdminUserStatusFilter | null; label: string }> = [
  { value: null, label: "Все" },
  { value: "active", label: "Активные" },
  { value: "banned", label: "Забаненные" },
  { value: "frozen", label: "Заморожены" },
];

const ROLE_VALUES = new Set<AdminUserRoleFilter>(["admin", "arbiter", "vip", "regular"]);
const STATUS_VALUES = new Set<AdminUserStatusFilter>(["active", "banned", "frozen"]);

function parseRoleParam(raw: string | null): AdminUserRoleFilter | undefined {
  return raw && ROLE_VALUES.has(raw as AdminUserRoleFilter) ? (raw as AdminUserRoleFilter) : undefined;
}

function parseStatusParam(raw: string | null): AdminUserStatusFilter | undefined {
  return raw && STATUS_VALUES.has(raw as AdminUserStatusFilter) ? (raw as AdminUserStatusFilter) : undefined;
}

/**
 * Continental admin users list.
 *
 * URL-driven so deep-links from the dashboard (`?status=banned`,
 * `?role=admin`) seed the filters. Search input is debounced via local
 * state only — query refetches on Enter / blur to keep traffic minimal.
 */
export default function AdminUsersPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [draftQ, setDraftQ] = useState(searchParams.get("q") ?? "");
  const [showFilters, setShowFilters] = useState(false);

  const role = parseRoleParam(searchParams.get("role"));
  const status = parseStatusParam(searchParams.get("status"));
  const page = parsePositiveIntRouteParam(searchParams.get("page") ?? undefined) ?? 1;
  const q = searchParams.get("q") ?? "";

  const query: AdminListUsersQuery = { q, role, status, page, page_size: 20 };
  const { data, isLoading } = useAdminUsers(query);

  const __guard = useAdminRedirect();
  if (!__guard.shouldRender) return null;

  const update = (next: Partial<AdminListUsersQuery>) => {
    const sp = new URLSearchParams(searchParams);
    for (const [k, v] of Object.entries(next)) {
      // Audit L-10 — ``null``/``undefined``/empty string all mean
      // "clear the filter". The legacy ``"any"`` sentinel is gone.
      if (v === undefined || v === null || v === "") {
        sp.delete(k);
      } else {
        sp.set(k, String(v));
      }
    }
    if (!("page" in next)) sp.delete("page");
    setSearchParams(sp, { replace: true });
  };

  return (
    <Page showBack onBack={() => navigate(-1)}>
      <AdminHeader
        title="Пользователи"
        subtitle={data ? `${data.total} всего` : undefined}
        right={
          <button
            type="button"
            onClick={() => setShowFilters((v) => !v)}
            className="rounded-button bg-panel p-2 text-text-muted active:scale-95"
            aria-label="Фильтры"
          >
            <Filter size={18} />
          </button>
        }
      />

      <div className="px-4 mb-3 flex items-center gap-2">
        <div className="flex-1 flex items-center gap-2 bg-panel rounded-button px-3 py-2">
          <Search size={16} className="text-text-muted" />
          <input
            value={draftQ}
            onChange={(e) => setDraftQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") update({ q: draftQ.trim() || undefined });
            }}
            onBlur={() => {
              if (draftQ.trim() !== q) update({ q: draftQ.trim() || undefined });
            }}
            placeholder="@username или tg_id"
            className="flex-1 bg-transparent outline-none text-sm"
          />
        </div>
      </div>

      {showFilters && (
        <div className="px-4 space-y-3 mb-3">
          <FilterRow
            label="Роль"
            options={ROLES}
            value={role ?? null}
            onChange={(v) => update({ role: v ?? undefined })}
          />
          <FilterRow
            label="Статус"
            options={STATUSES}
            value={status ?? null}
            onChange={(v) => update({ status: v ?? undefined })}
          />
        </div>
      )}

      <div className="px-4 space-y-2">
        {isLoading
          ? Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-16 rounded-card" />
            ))
          : data?.items.length === 0
            ? (
              <p className="text-sm text-text-muted text-center py-12">
                Никого не найдено
              </p>
            )
            : data?.items.map((u) => (
                <UserRow
                  key={u.id}
                  user={u}
                  onClick={() => navigate(`/admin/users/${u.id}`)}
                />
              ))}
      </div>

      {data && data.total > data.page_size && (
        <Pagination
          page={data.page}
          total={data.total}
          pageSize={data.page_size}
          onChange={(next) => {
            const sp = new URLSearchParams(searchParams);
            sp.set("page", String(next));
            setSearchParams(sp, { replace: true });
          }}
        />
      )}
    </Page>
  );
}

// Audit L-10 — ``value`` is ``T | null`` so the "no filter" sentinel is
// a real ``null`` instead of a magic string. ``T`` itself stays narrow
// (e.g. ``"admin" | "arbiter" | ...``) so a typo in the options list
// is still caught at compile time.
interface FilterOption<T extends string> {
  value: T | null;
  label: string;
}

function FilterRow<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: FilterOption<T>[];
  value: T | null;
  onChange: (v: T | null) => void;
}) {
  return (
    <div>
      <p className="text-xs text-text-muted mb-1.5">{label}</p>
      <div className="flex flex-wrap gap-1.5">
        {options.map((opt) => {
          const active = opt.value === value;
          return (
            <button
              key={opt.value ?? "__none__"}
              type="button"
              onClick={() => onChange(opt.value)}
              className={`rounded-button px-3 py-1.5 text-sm transition ${
                active
                  ? "bg-accent text-accent-fg font-medium"
                  : "bg-panel text-text-muted"
              }`}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function UserRow({ user, onClick }: { user: AdminUserListItemDto; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full flex items-center gap-3 bg-panel rounded-card p-3 text-left active:scale-[0.98] transition"
    >
      <div className="w-10 h-10 rounded-full bg-panel-2 overflow-hidden flex-shrink-0">
        {user.photo_url && (
          <img src={user.photo_url} alt="" className="w-full h-full object-cover" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="font-medium truncate">{user.display_name}</span>
          {user.prefix && <BadgePrefix prefix={user.prefix} />}
        </div>
        <div className="text-xs text-text-muted truncate">
          @{user.username ?? "—"} · tg {user.tg_user_id}
        </div>
        <div className="text-xs text-text-muted">
          Сделок: {user.deals_total} · ★ {user.rating.toFixed(1)} · Траст ${user.trust_deposit_balance.toFixed(2)}
        </div>
      </div>
      <div className="flex flex-col items-end gap-1">
        {user.is_banned && (
          <span className="text-[10px] uppercase font-semibold text-danger">
            Бан
          </span>
        )}
        {user.is_frozen && (
          <span className="text-[10px] uppercase font-semibold text-warning">
            Заморожен
          </span>
        )}
      </div>
    </button>
  );
}

function Pagination({
  page,
  total,
  pageSize,
  onChange,
}: {
  page: number;
  total: number;
  pageSize: number;
  onChange: (next: number) => void;
}) {
  const totalPages = Math.ceil(total / pageSize);
  return (
    <div className="flex items-center justify-center gap-2 mt-4 px-4">
      <button
        type="button"
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
        className="rounded-button bg-panel p-2 disabled:opacity-40"
        aria-label="Назад"
      >
        <ChevronLeft size={18} />
      </button>
      <span className="text-sm tabular-nums text-text-muted px-3">
        {page} / {totalPages}
      </span>
      <button
        type="button"
        disabled={page >= totalPages}
        onClick={() => onChange(page + 1)}
        className="rounded-button bg-panel p-2 disabled:opacity-40"
        aria-label="Вперёд"
      >
        <ChevronRight size={18} />
      </button>
    </div>
  );
}
