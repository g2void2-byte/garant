import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Coins, Tags, Plus, Pencil } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Skeleton } from "@/components/ui/Skeleton";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Switch } from "@/components/ui/Switch";
import { useToast } from "@/components/ui/Toast";
import { confirmDialog } from "@/lib/dialog";
import {
  useAdminCategories,
  useAdminCurrencies,
  useAdminDeleteCategory,
  useAdminUpsertCategory,
  useAdminUpsertCurrency,
} from "@/api/admin/hooks";
import type {
  AdminCategoryDto,
  AdminCurrencyDto,
} from "@/api/types";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";

export default function AdminTaxonomyPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<"categories" | "currencies">("categories");
  const __guard = useAdminRedirect();
  if (!__guard.shouldRender) return null;
  return (
    <Page showBack onBack={() => navigate("/admin")}>
      <Header title="Таксономия" />
      <div className="px-4 mb-3 flex gap-1.5">
        <button
          type="button"
          onClick={() => setTab("categories")}
          className={`flex-1 rounded-button py-2 text-sm transition ${
            tab === "categories"
              ? "bg-accent text-accent-fg font-medium"
              : "bg-panel text-text-muted"
          }`}
        >
          <Tags size={14} className="inline mr-1" /> Категории
        </button>
        <button
          type="button"
          onClick={() => setTab("currencies")}
          className={`flex-1 rounded-button py-2 text-sm transition ${
            tab === "currencies"
              ? "bg-accent text-accent-fg font-medium"
              : "bg-panel text-text-muted"
          }`}
        >
          <Coins size={14} className="inline mr-1" /> Валюты
        </button>
      </div>
      {tab === "categories" ? <CategoriesPane /> : <CurrenciesPane />}
    </Page>
  );
}

function CategoriesPane() {
  const { data, isLoading } = useAdminCategories();
  const del = useAdminDeleteCategory();
  const [editing, setEditing] = useState<AdminCategoryDto | "new" | null>(null);
  const toast = useToast();
  return (
    <div className="px-4 space-y-2 pb-24">
      <Button
        type="button"
        variant="ghost"
        onClick={() => setEditing("new")}
        className="w-full"
      >
        <Plus size={14} className="mr-1" /> Добавить
      </Button>
      {isLoading ? (
        Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-14 rounded-card" />
        ))
      ) : (
        data?.map((c, _idx) => (
          <div
            key={c.id}
            className="bg-panel rounded-card p-3 flex items-center gap-3"
          >
            <div className="text-2xl">{c.icon || "📦"}</div>
            <div className="flex-1 min-w-0">
              <div className="font-medium truncate">{c.name}</div>
              <div className="text-xs text-text-muted">{c.slug}</div>
            </div>
            <button
              type="button"
              onClick={() => setEditing(c)}
              className="text-text-muted active:scale-90"
            >
              <Pencil size={16} />
            </button>
            <button
              type="button"
              onClick={async () => {
                // Audit L-15 — ``confirmDialog`` prefers Telegram’s native
                // ``showConfirm``; falls back to ``window.confirm`` outside Telegram.
                if (!(await confirmDialog(`Удалить категорию ${c.name}?`))) return;
                try {
                  await del.mutateAsync(c.id);
                  toast.show({ kind: "info", title: "Удалено" });
                } catch (e) {
                  toast.show({
                    kind: "error",
                    title: "Ошибка",
                    body: (e as Error).message,
                  });
                }
              }}
              className="text-danger text-xs"
            >
              ×
            </button>
          </div>
        ))
      )}
      <Sheet
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing === "new" ? "Новая категория" : "Категория"}
      >
        {editing !== null && (
          <CategoryForm
            initial={editing === "new" ? null : editing}
            onDone={() => setEditing(null)}
          />
        )}
      </Sheet>
    </div>
  );
}

function CategoryForm({
  initial,
  onDone,
}: {
  initial: AdminCategoryDto | null;
  onDone: () => void;
}) {
  const [slug, setSlug] = useState(initial?.slug ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [icon, setIcon] = useState(initial?.icon ?? "");
  const upsert = useAdminUpsertCategory();
  const toast = useToast();
  return (
    <div className="space-y-3">
      <div>
        <label className="block text-xs text-text-muted mb-1">Slug</label>
        <Input
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          disabled={!!initial}
        />
      </div>
      <div>
        <label className="block text-xs text-text-muted mb-1">Название</label>
        <Input value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div>
        <label className="block text-xs text-text-muted mb-1">Иконка (emoji)</label>
        <Input value={icon} onChange={(e) => setIcon(e.target.value)} />
      </div>
      <Button
        type="button"
        disabled={!slug || !name || upsert.isPending}
        onClick={async () => {
          try {
            await upsert.mutateAsync({ slug, name, icon: icon || undefined });
            toast.show({ kind: "success", title: "Сохранено" });
            onDone();
          } catch (e) {
            toast.show({
              kind: "error",
              title: "Ошибка",
              body: (e as Error).message,
            });
          }
        }}
        className="w-full"
      >
        Сохранить
      </Button>
    </div>
  );
}

function CurrenciesPane() {
  const { data, isLoading } = useAdminCurrencies();
  const [editing, setEditing] = useState<AdminCurrencyDto | "new" | null>(null);
  return (
    <div className="px-4 space-y-2 pb-24">
      <Button
        type="button"
        variant="ghost"
        onClick={() => setEditing("new")}
        className="w-full"
      >
        <Plus size={14} className="mr-1" /> Добавить
      </Button>
      {isLoading ? (
        Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-14 rounded-card" />
        ))
      ) : (
        data?.map((c, _idx) => (
          <div
            key={c.id}
            className="bg-panel rounded-card p-3 flex items-center gap-3"
          >
            <div className="flex-1">
              <div className="font-medium">
                {c.code}
                {!c.is_active && (
                  <span className="ml-2 text-[10px] text-warning">off</span>
                )}
              </div>
              <div className="text-xs text-text-muted">
                {c.name} · {c.network} · мин: {c.min_deposit}/{c.min_withdraw}
              </div>
            </div>
            <button
              type="button"
              onClick={() => setEditing(c)}
              className="text-text-muted active:scale-90"
            >
              <Pencil size={16} />
            </button>
          </div>
        ))
      )}
      <Sheet
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing === "new" ? "Новая валюта" : "Валюта"}
      >
        {editing !== null && (
          <CurrencyForm
            initial={editing === "new" ? null : editing}
            onDone={() => setEditing(null)}
          />
        )}
      </Sheet>
    </div>
  );
}

function CurrencyForm({
  initial,
  onDone,
}: {
  initial: AdminCurrencyDto | null;
  onDone: () => void;
}) {
  const [code, setCode] = useState(initial?.code ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [network, setNetwork] = useState(initial?.network ?? "");
  const [decimals, setDecimals] = useState(String(initial?.decimals ?? 2));
  const [minDeposit, setMinDeposit] = useState(String(initial?.min_deposit ?? 0));
  const [minWithdraw, setMinWithdraw] = useState(String(initial?.min_withdraw ?? 0));
  const [isActive, setIsActive] = useState(initial?.is_active ?? true);
  const upsert = useAdminUpsertCurrency();
  const toast = useToast();
  return (
    <div className="space-y-3">
      <div>
        <label className="block text-xs text-text-muted mb-1">Код</label>
        <Input
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          disabled={!!initial}
        />
      </div>
      <div>
        <label className="block text-xs text-text-muted mb-1">Название</label>
        <Input value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div>
        <label className="block text-xs text-text-muted mb-1">Сеть</label>
        <Input
          value={network}
          onChange={(e) => setNetwork(e.target.value)}
          placeholder="TON / TRC20 / ERC20"
        />
      </div>
      <div className="grid grid-cols-3 gap-2">
        <div>
          <label className="block text-xs text-text-muted mb-1">Decimals</label>
          <Input
            inputMode="numeric"
            value={decimals}
            onChange={(e) => setDecimals(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs text-text-muted mb-1">Min deposit</label>
          <Input
            inputMode="decimal"
            value={minDeposit}
            onChange={(e) => setMinDeposit(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs text-text-muted mb-1">Min withdraw</label>
          <Input
            inputMode="decimal"
            value={minWithdraw}
            onChange={(e) => setMinWithdraw(e.target.value)}
          />
        </div>
      </div>
      <div className="bg-panel-2 rounded-button px-3 py-2">
        <Switch checked={isActive} onChange={setIsActive} label="Активна" />
      </div>
      <Button
        type="button"
        disabled={!code || upsert.isPending}
        onClick={async () => {
          try {
            await upsert.mutateAsync({
              code,
              name: name || undefined,
              network: network || undefined,
              decimals: Number(decimals),
              min_deposit: Number(minDeposit),
              min_withdraw: Number(minWithdraw),
              is_active: isActive,
            });
            toast.show({ kind: "success", title: "Сохранено" });
            onDone();
          } catch (e) {
            toast.show({
              kind: "error",
              title: "Ошибка",
              body: (e as Error).message,
            });
          }
        }}
        className="w-full"
      >
        Сохранить
      </Button>
    </div>
  );
}
