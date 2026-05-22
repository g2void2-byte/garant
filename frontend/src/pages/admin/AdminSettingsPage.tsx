import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Save, Lock, AlertTriangle } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { AdminHeader } from "@/components/layout/AdminHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Switch } from "@/components/ui/Switch";
import { useToast } from "@/components/ui/Toast";
import { useAdminSettings, useAdminUpdateSettings } from "@/api/admin/hooks";
import type { AdminSettingsDto } from "@/api/types";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";

/**
 * `/admin/settings` — global app configuration.
 *
 * Single PATCH endpoint accepts any subset, so the form diff-saves
 * only the fields the admin actually changed. Maintenance toggle is
 * highlighted in danger color because flipping it blocks every
 * non-admin write across both bot and TMA.
 */
export default function AdminSettingsPage() {
  const navigate = useNavigate();
  const { data, isLoading } = useAdminSettings();
  const update = useAdminUpdateSettings();
  const toast = useToast();
  const [form, setForm] = useState<AdminSettingsDto | null>(null);

  useEffect(() => {
    if (data && !form) setForm(data);
  }, [data, form]);

  const __guard = useAdminRedirect();
  if (!__guard.shouldRender) return null;

  if (isLoading || !form) {
    return (
      <Page showBack onBack={() => navigate("/admin")}>
        <AdminHeader title="Настройки" />
        <div className="px-4 space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-card" />
          ))}
        </div>
      </Page>
    );
  }

  const diff: Partial<AdminSettingsDto> = {};
  if (data) {
    for (const k of Object.keys(form) as (keyof AdminSettingsDto)[]) {
      if (form[k] !== data[k]) (diff as Record<string, unknown>)[k] = form[k];
    }
  }
  const dirty = Object.keys(diff).length > 0;

  return (
    <Page showBack onBack={() => navigate("/admin")}>
      <AdminHeader title="Настройки" subtitle={dirty ? "Несохранённые изменения" : undefined} />
      <div className="px-4 space-y-4 pb-24">
        <Section title="Комиссии (%)">
          <Row label="Обычная комиссия (сделки)">
            <NumberField
              value={form.deal_commission_percent}
              onChange={(v) => setForm({ ...form, deal_commission_percent: v })}
            />
          </Row>
          <Row label="Комиссия по счетам">
            <NumberField
              value={form.invoice_commission_percent}
              onChange={(v) => setForm({ ...form, invoice_commission_percent: v })}
            />
          </Row>
          <Row label="VIP комиссия (−1 = такая же как обычная)">
            <NumberField
              value={form.vip_commission_percent}
              onChange={(v) => setForm({ ...form, vip_commission_percent: v })}
            />
          </Row>
        </Section>

        <Section title="Лимиты и тайминги">
          <Row label="Мин. депозит (USD)">
            <NumberField
              value={form.min_deposit}
              onChange={(v) => setForm({ ...form, min_deposit: v })}
            />
          </Row>
          <Row label="Мин. вывод (USD)">
            <NumberField
              value={form.min_withdraw}
              onChange={(v) => setForm({ ...form, min_withdraw: v })}
            />
          </Row>
          <Row label="Авто-истечение pending payment (дни)">
            <NumberField
              value={form.inactivity_pending_confirmation_days}
              onChange={(v) =>
                setForm({ ...form, inactivity_pending_confirmation_days: v })
              }
            />
          </Row>
          <Row label="Авто-cancellation (дни)">
            <NumberField
              value={form.inactivity_pending_cancellation_days}
              onChange={(v) =>
                setForm({ ...form, inactivity_pending_cancellation_days: v })
              }
            />
          </Row>
          <Row label="Максимум активных услуг на юзера">
            <NumberField
              value={form.max_active_services_per_user}
              onChange={(v) => setForm({ ...form, max_active_services_per_user: v })}
            />
          </Row>
        </Section>

        <Section title="Платежи">
          <Row label="Авто-вывод через CryptoBot">
            <Switch
              checked={form.auto_withdraw_enabled}
              onChange={(c) => setForm({ ...form, auto_withdraw_enabled: c })}
            />
          </Row>
        </Section>

        <Section title="Технические работы" danger>
          <Row label="Включить maintenance">
            <Switch
              checked={form.maintenance_enabled}
              onChange={(c) => setForm({ ...form, maintenance_enabled: c })}
            />
          </Row>
          <div className="px-3">
            <label className="text-xs text-text-muted">Сообщение в баннере</label>
            <Input
              value={form.maintenance_message}
              onChange={(e) =>
                setForm({ ...form, maintenance_message: e.target.value })
              }
            />
          </div>
          {form.maintenance_enabled && (
            <div
              className="mx-3 p-2.5 rounded-card bg-danger/10 border border-danger/30 text-danger text-xs flex items-start gap-2"
            >
              <AlertTriangle size={14} className="shrink-0 mt-0.5" />
              <span>
                При сохранении бот и TMA перестанут принимать любые
                действия (кроме админских) пока флаг не выключен.
              </span>
            </div>
          )}
        </Section>
      </div>

      <div className="fixed bottom-4 left-4 right-4 z-40">
        <Button
          type="button"
          disabled={!dirty || update.isPending}
          onClick={async () => {
            try {
              const saved = await update.mutateAsync(diff);
              setForm(saved);
              toast.show({ kind: "success", title: "Сохранено" });
            } catch (e) {
              toast.show({ kind: "error", title: "Ошибка", body: (e as Error).message });
            }
          }}
          className="w-full"
        >
          {update.isPending ? (
            <Lock size={14} className="mr-1" />
          ) : (
            <Save size={14} className="mr-1" />
          )}
          Сохранить {dirty ? `(${Object.keys(diff).length})` : ""}
        </Button>
      </div>
    </Page>
  );
}

function Section({
  title,
  children,
  danger,
}: {
  title: string;
  children: React.ReactNode;
  danger?: boolean;
}) {
  return (
    <div
      className={`rounded-card overflow-hidden ${
        danger ? "bg-danger/5 border border-danger/30" : "bg-panel"
      }`}
    >
      <div className="px-3 pt-3 pb-1 text-xs text-text-muted uppercase tracking-wider">
        {title}
      </div>
      <div className="space-y-2 py-2">{children}</div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between px-3 py-1.5">
      <span className="text-sm flex-1">{label}</span>
      <div className="ml-3">{children}</div>
    </div>
  );
}

function NumberField({
  value,
  onChange,
}: {
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <Input
      inputMode="decimal"
      value={String(value)}
      onChange={(e) => {
        const v = Number(e.target.value);
        if (!Number.isNaN(v)) onChange(v);
      }}
      className="!w-28 !text-right"
    />
  );
}
