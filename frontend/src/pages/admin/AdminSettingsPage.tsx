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
import type { AdminSettingsDto, AdminSettingsUpdateBody } from "@/api/types";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";
import { StatsBadge } from "@/components/domain/StatsBadge";
import {
  parseNonNegativeDecimalInput,
  parseNonNegativeIntInput,
  parseSignedDecimalInput,
} from "@/lib/formNumbers";

type DecimalSettingsKey =
  | "deal_commission_percent"
  | "vip_commission_percent"
  | "pin_reset_price_usd"
  | "faq_stats_total_usd";

type AdminSettingsForm = Omit<AdminSettingsDto, DecimalSettingsKey> &
  Record<DecimalSettingsKey, number | string>;

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
  const [form, setForm] = useState<AdminSettingsForm | null>(null);

  useEffect(() => {
    if (data && !form) setForm(data);
  }, [data, form]);

  const __guard = useAdminRedirect();
  if (!__guard.shouldRender) return null;

  if (isLoading || !form) {
    return (
      <Page showBack onBack={() => navigate(-1)}>
        <AdminHeader title="Настройки" />
        <div className="px-4 space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-card" />
          ))}
        </div>
      </Page>
    );
  }

  const diff: AdminSettingsUpdateBody = {};
  if (data) {
    for (const k of Object.keys(form) as (keyof AdminSettingsForm)[]) {
      if (form[k] !== data[k]) (diff as Record<string, unknown>)[k] = form[k];
    }
  }
  const dirty = Object.keys(diff).length > 0;

  return (
    <Page showBack onBack={() => navigate(-1)}>
      <AdminHeader title="Настройки" subtitle={dirty ? "Несохранённые изменения" : undefined} />
      <div className="px-4 space-y-4 pb-24">
        <Section title="Плашка статистики на FAQ">
          <Row label="Показывать на /faq">
            <Switch
              checked={form.faq_stats_badge_enabled}
              onChange={(c) =>
                setForm({ ...form, faq_stats_badge_enabled: c })
              }
            />
          </Row>
          <Row label="Пользователей">
            <NumberField
              value={form.faq_stats_users}
              parse={parseNonNegativeIntInput}
              inputMode="numeric"
              onChange={(v) => setForm({ ...form, faq_stats_users: Number(v) })}
            />
          </Row>
          <Row label="Сделок">
            <NumberField
              value={form.faq_stats_deals}
              parse={parseNonNegativeIntInput}
              inputMode="numeric"
              onChange={(v) => setForm({ ...form, faq_stats_deals: Number(v) })}
            />
          </Row>
          <Row label="Объём (USD)">
            <NumberField
              value={form.faq_stats_total_usd}
              parse={parseNonNegativeDecimalInput}
              preserveDecimalString
              onChange={(v) => setForm({ ...form, faq_stats_total_usd: v })}
            />
          </Row>
          <div className={`px-3 pb-2 ${form.faq_stats_badge_enabled ? "" : "opacity-55"}`}>
            <div className="mb-2 text-[11px] uppercase tracking-wider text-text-muted">
              Превью плашки
            </div>
            <StatsBadge
              variant="compact"
              stats={{
                users: form.faq_stats_users,
                deals: form.faq_stats_deals,
                total_usd: form.faq_stats_total_usd,
              }}
              title="FAQ EW Гарант"
              subtitle={
                form.faq_stats_badge_enabled
                  ? "Показывается на /faq"
                  : "Сейчас скрыта — включите переключатель, чтобы показать на /faq"
              }
            />
            <div className="mt-3">
              <Button
                type="button"
                className="w-full"
                disabled={update.isPending}
                onClick={async () => {
                  try {
                    const saved = await update.mutateAsync({
                      faq_stats_badge_enabled: form.faq_stats_badge_enabled,
                      faq_stats_users: form.faq_stats_users,
                      faq_stats_deals: form.faq_stats_deals,
                      faq_stats_total_usd: form.faq_stats_total_usd,
                    });
                    setForm(saved);
                    toast.show({ kind: "success", title: "Плашка сохранена" });
                  } catch (e) {
                    toast.show({ kind: "error", title: "Ошибка", body: (e as Error).message });
                  }
                }}
              >
                Сохранить плашку FAQ
              </Button>
            </div>
          </div>
        </Section>

        <Section title="Комиссии (%)">
          <Row label="Обычная комиссия (сделки)">
            <NumberField
              value={form.deal_commission_percent}
              parse={parseRegularCommissionPercent}
              preserveDecimalString
              onChange={(v) => setForm({ ...form, deal_commission_percent: v })}
            />
          </Row>
          <Row label="VIP комиссия (−1 = такая же как обычная)">
            <NumberField
              value={form.vip_commission_percent}
              parse={parseVipCommissionPercent}
              preserveDecimalString
              onChange={(v) => setForm({ ...form, vip_commission_percent: v })}
            />
          </Row>
        </Section>

        <Section title="Лимиты и тайминги">
          <Row label="Авто-истечение pending payment (дни)">
            <NumberField
              value={form.inactivity_pending_confirmation_days}
              parse={parseNonNegativeIntInput}
              inputMode="numeric"
              onChange={(v) =>
                setForm({ ...form, inactivity_pending_confirmation_days: Number(v) })
              }
            />
          </Row>
          <Row label="Авто-cancellation (дни)">
            <NumberField
              value={form.inactivity_pending_cancellation_days}
              parse={parseNonNegativeIntInput}
              inputMode="numeric"
              onChange={(v) =>
                setForm({ ...form, inactivity_pending_cancellation_days: Number(v) })
              }
            />
          </Row>
          <Row label="Истечение pending topup (часы)">
            <NumberField
              value={form.pending_topup_expiry_hours}
              parse={parseNonNegativeIntInput}
              inputMode="numeric"
              onChange={(v) => setForm({ ...form, pending_topup_expiry_hours: Number(v) })}
            />
          </Row>
          <Row label="Максимум активных услуг на юзера">
            <NumberField
              value={form.max_active_services_per_user}
              parse={parseNonNegativeIntInput}
              inputMode="numeric"
              onChange={(v) => setForm({ ...form, max_active_services_per_user: Number(v) })}
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
          <Row label="Цена восстановления PIN ($)">
            <NumberField
              value={form.pin_reset_price_usd ?? 0}
              parse={parseNonNegativeDecimalInput}
              preserveDecimalString
              onChange={(v) => setForm({ ...form, pin_reset_price_usd: v })}
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

      <div className="fixed bottom-24 left-4 right-4 z-50">
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
  parse = parseNonNegativeDecimalInput,
  inputMode = "decimal",
  preserveDecimalString = false,
}: {
  value: number | string;
  onChange: (v: number | string) => void;
  parse?: (raw: string) => number | null;
  inputMode?: "decimal" | "numeric";
  preserveDecimalString?: boolean;
}) {
  return (
    <Input
      inputMode={inputMode}
      value={String(value)}
      onChange={(e) => {
        const raw = e.target.value;
        const v = parse(raw);
        if (v !== null) onChange(preserveDecimalString ? raw.trim() : v);
      }}
      className="!w-28 !text-right"
    />
  );
}

function parseRegularCommissionPercent(raw: string): number | null {
  const parsed = parseNonNegativeDecimalInput(raw);
  return parsed !== null && parsed <= 100 ? parsed : null;
}

function parseVipCommissionPercent(raw: string): number | null {
  const parsed = parseSignedDecimalInput(raw);
  return parsed !== null && parsed >= -1 && parsed <= 100 ? parsed : null;
}
