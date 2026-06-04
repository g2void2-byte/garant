import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  Check,
  CornerDownRight,
  DollarSign,
  Gavel,
  Lock,
  Send,
  Split,
  Trash2,
  Undo2,
  UserCheck,
} from "lucide-react";
import { Page } from "@/components/layout/Page";
import { AdminHeader } from "@/components/layout/AdminHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { Button } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { useToast } from "@/components/ui/Toast";
import {
  useAdminApproveDealApproval,
  useAdminAssignArbiter,
  useAdminDeal,
  useAdminDeleteDeal,
  useAdminForceArbitration,
  useAdminForceRefund,
  useAdminForceRelease,
  useAdminRejectDealApproval,
  useAdminSplitDeal,
} from "@/api/admin/hooks";
import {
  DEAL_MESSAGE_PAGE_SIZE,
  useDealMessages,
  useLoadOlderDealMessages,
  useMe,
  useSendDealMessage,
} from "@/api/hooks";
import { formatDateTime, parseDecimal } from "@/lib/format";
import {
  parseNonNegativeDecimalInput,
  parseNonNegativeIntInput,
} from "@/lib/formNumbers";
import type {
  AdminDealDetailDto,
  AdminBalanceSnapshotDto,
  AdminUserListDto,
} from "@/api/types";
import { api } from "@/api/client";
import { haptic } from "@/lib/tg";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";
import { parsePositiveIntRouteParam } from "@/lib/routeParams";
import { formatAdminUsername } from "./format";

const STATUS_LABEL: Record<string, string> = {
  cancelled: "Отменена",
  pending_confirmation: "Подтверждение",
  pending_payment: "Ожидание оплаты",
  pending_topup: "Ожидание инвойса",
  in_progress: "В работе",
  completed: "Завершена",
  arbitration: "Арбитраж",
  resolved_for_buyer: "В пользу покупателя",
  resolved_for_seller: "В пользу продавца",
  pending_cancellation: "Запрошена отмена",
  cancelled_for_inactivity: "Отменена по неактивности",
};

const EVENT_KIND: Record<string, string> = {
  created: "Создана",
  in_progress: "Запущена",
  cancel_request: "Запрос отмены",
  arbitration_started: "Открыт арбитраж",
  arbitration_resolved: "Арбитраж решён",
  completed: "Завершена",
  cancelled: "Отменена",
};

const TERMINAL = new Set([
  "completed",
  "cancelled",
  "resolved_for_buyer",
  "resolved_for_seller",
  "cancelled_for_inactivity",
]);

function parsePositiveIntInput(raw: string): number | null {
  const parsed = parseNonNegativeIntInput(raw);
  return parsed !== null && parsed > 0 ? parsed : null;
}

function parseSplitPercentInput(raw: string): number | null {
  const parsed = parseNonNegativeDecimalInput(raw);
  return parsed !== null && parsed <= 100 ? parsed : null;
}

/**
 * Continental admin deal detail page.
 *
 * Layout (top → bottom):
 *   1. Status banner (Заглавный статус сделки + флаги).
 *   2. Balance snapshot (buyer/seller карточки).
 *   3. Action panel (force-release/refund/split/arbitration/assign/delete).
 *   4. Audit timeline (reverse chronological).
 *   5. Chat — read-only feed + одно поле для ответа админа в чат сделки.
 */
export default function AdminDealDetailPage() {
  const { id } = useParams<{ id: string }>();
  const dealId = parsePositiveIntRouteParam(id);
  const navigate = useNavigate();
  const { data: me } = useMe();
  const { data: deal, isLoading } = useAdminDeal(dealId);

  const __guard = useAdminRedirect({ allowArbiter: true });
  if (!__guard.shouldRender) return null;

  if (!dealId) {
    return (
      <Page showBack onBack={() => navigate(-1)}>
        <AdminHeader title="Сделка" />
        <p className="px-4 text-sm text-text-muted">Неверный ID.</p>
      </Page>
    );
  }

  return (
    <Page showBack onBack={() => navigate(-1)}>
      <AdminHeader
        title={deal ? `Сделка #${deal.id}` : "Сделка"}
        subtitle={deal ? STATUS_LABEL[deal.status] ?? deal.status : undefined}
      />
      {isLoading || !deal ? (
        <div className="px-4 space-y-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-24" />
          <Skeleton className="h-40" />
        </div>
      ) : (
        <div className="px-4 space-y-4 pb-8">
          <StatusBanner deal={deal} />
          <BalanceSnapshotCard
            buyer={deal.buyer}
            seller={deal.seller}
            amount={deal.amount}
            commission={deal.commission_amount}
            commissionPaid={deal.commission_paid}
            topupDepositId={deal.topup_deposit_id}
          />
          {me?.is_admin && <ActionPanel deal={deal} currentAdminId={me.id} />}
          <EventsTimeline deal={deal} />
          <MessagesFeed deal={deal} />
        </div>
      )}
    </Page>
  );
}

// ── Status ────────────────────────────────────────────────────────────────

function StatusBanner({ deal }: { deal: AdminDealDetailDto }) {
  const isArb = deal.status === "arbitration";
  const hasCancel = deal.cancellation_requested_at && !TERMINAL.has(deal.status);
  return (
    <section
      className={`rounded-card p-4 ${
        isArb ? "bg-danger/10 border border-danger/30" : hasCancel ? "bg-warning/10 border border-warning/30" : "bg-panel"
      }`}
    >
      <div className="text-xs uppercase tracking-wide text-text-muted mb-1">{deal.description || "—"}</div>
      <div className="text-base font-semibold flex items-center gap-2">
        {isArb && <Gavel size={16} className="text-danger" />}
        {hasCancel && <AlertTriangle size={16} className="text-warning" />}
        {STATUS_LABEL[deal.status] ?? deal.status}
      </div>
      {deal.cancellation_reason && (
        <div className="mt-2 text-xs text-warning">Причина отмены: {deal.cancellation_reason}</div>
      )}
      {deal.arbitration_reason && (
        <div className="mt-2 text-xs text-danger">Причина арбитража: {deal.arbitration_reason}</div>
      )}
      {deal.arbitration_resolution && (
        <div className="mt-2 text-xs text-text-muted">Решение: {deal.arbitration_resolution}</div>
      )}
    </section>
  );
}

// ── Balance snapshot ──────────────────────────────────────────────────────

function BalanceSnapshotCard({
  buyer,
  seller,
  amount,
  commission,
  commissionPaid,
  topupDepositId,
}: {
  buyer: AdminBalanceSnapshotDto;
  seller: AdminBalanceSnapshotDto;
  amount: string;
  commission: string | null;
  commissionPaid: boolean;
  topupDepositId?: number | null;
}) {
  return (
    <section className="grid grid-cols-2 gap-3">
      <PartyCard side="Покупатель" snap={buyer} />
      <PartyCard side="Продавец" snap={seller} />
      <div className="col-span-2 bg-panel rounded-card p-3 flex items-center justify-between text-sm">
        <div className="flex items-center gap-2">
          <DollarSign size={14} className="text-text-muted" /> Сумма сделки
        </div>
        <div className="font-semibold">${parseDecimal(amount).toFixed(2)}</div>
      </div>
      {commission !== null && (
        <div className="col-span-2 bg-panel rounded-card p-3 flex items-center justify-between text-sm">
          <div className="flex items-center gap-2">
            <Lock size={14} className="text-text-muted" /> Комиссия
          </div>
          <div className="text-right">
            <div className="font-semibold">{parseDecimal(commission).toFixed(2)}</div>
            <div className="text-[11px] text-text-muted">
              {commissionPaid ? "оплачена" : "ожидает оплаты"}
              {topupDepositId ? ` · депозит #${topupDepositId}` : ""}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function PartyCard({ side, snap }: { side: string; snap: AdminBalanceSnapshotDto }) {
  return (
    <div className="bg-panel rounded-card p-3">
      <div className="text-[11px] uppercase tracking-wide text-text-muted">{side}</div>
      <div className="mt-1 font-semibold truncate">{snap.display_name}</div>
      <div className="text-xs text-text-muted truncate">{formatAdminUsername(snap.username)} · id {snap.user_id}</div>
      <div className="mt-2 text-xs text-text-muted">
        Свободно <span className="text-text font-medium">{parseDecimal(snap.amount).toFixed(4)}</span>{" "}
        {snap.currency_code ?? "USD"}
      </div>
      <div className="text-xs text-text-muted">
        В сделке <span className="text-text font-medium">{parseDecimal(snap.locked).toFixed(4)}</span>{" "}
        {snap.currency_code ?? "USD"}
      </div>
    </div>
  );
}

// ── Actions ───────────────────────────────────────────────────────────────

function ActionPanel({ deal, currentAdminId }: { deal: AdminDealDetailDto; currentAdminId?: number }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [sheet, setSheet] = useState<null | "release" | "refund" | "split" | "arbitration" | "assign" | "delete">(null);
  const release = useAdminForceRelease();
  const refund = useAdminForceRefund();
  const split = useAdminSplitDeal();
  const approve = useAdminApproveDealApproval();
  const reject = useAdminRejectDealApproval();
  const arb = useAdminForceArbitration();
  const assign = useAdminAssignArbiter();
  const del = useAdminDeleteDeal();
  const [reason, setReason] = useState("");
  const [splitBuyerPct, setSplitBuyerPct] = useState("50");
  const [approvalId, setApprovalId] = useState("");
  const [arbiterUsername, setArbiterUsername] = useState("");
  const terminal = TERMINAL.has(deal.status);
  const approvals = deal.pending_approvals ?? [];
  const hasApprovalId = approvalId.trim() !== "";
  const parsedApprovalId = hasApprovalId ? parsePositiveIntInput(approvalId) : null;
  const approvalIdError = hasApprovalId && parsedApprovalId === null
    ? "Введите положительный целый ID"
    : undefined;
  const parsedSplitBuyerPct = parseSplitPercentInput(splitBuyerPct);
  const splitBuyerPctError = parsedSplitBuyerPct === null
    ? "Введите число 0..100 без экспоненты"
    : undefined;

  const actionName = (action: "release" | "refund" | "split") => ({
    release: "deal.force_release",
    refund: "deal.force_refund",
    split: "deal.split",
  })[action];

  const approvedApprovalId = (action: "release" | "refund" | "split") => {
    if (parsedApprovalId !== null) return parsedApprovalId;
    return approvals.find((a) => a.status === "approved" && a.action === actionName(action))?.id;
  };

  const run = async (action: "release" | "refund" | "split" | "arbitration" | "assign" | "delete") => {
    haptic("light");
    try {
      if ((action === "release" || action === "refund" || action === "split") && approvalIdError) {
        toast.show({ kind: "error", title: "Неверный Approval ID" });
        return;
      }
      if (action === "release") {
        const result = await release.mutateAsync({ dealId: deal.id, body: { reason: reason || undefined, approval_id: approvedApprovalId("release") } });
        if ("pending_approval" in result && result.pending_approval) {
          toast.show({ kind: "success", title: "Needs second admin", body: `Approval #${result.pending_approval.id}` });
          setSheet(null);
          setReason("");
          setApprovalId("");
          return;
        }
        toast.show({ kind: "success", title: "Средства переданы продавцу" });
      } else if (action === "refund") {
        const result = await refund.mutateAsync({ dealId: deal.id, body: { reason: reason || undefined, approval_id: approvedApprovalId("refund") } });
        if ("pending_approval" in result && result.pending_approval) {
          toast.show({ kind: "success", title: "Needs second admin", body: `Approval #${result.pending_approval.id}` });
          setSheet(null);
          setReason("");
          setApprovalId("");
          return;
        }
        toast.show({ kind: "success", title: "Возврат покупателю" });
      } else if (action === "split") {
        if (parsedSplitBuyerPct === null) {
          toast.show({ kind: "error", title: "Доля покупателя должна быть 0..100" });
          return;
        }
        const result = await split.mutateAsync({
          dealId: deal.id,
          body: { buyer_percent: parsedSplitBuyerPct, reason: reason || undefined, approval_id: approvedApprovalId("split") },
        });
        if ("pending_approval" in result && result.pending_approval) {
          toast.show({ kind: "success", title: "Needs second admin", body: `Approval #${result.pending_approval.id}` });
          setSheet(null);
          setReason("");
          setApprovalId("");
          return;
        }
        toast.show({ kind: "success", title: `Сплит ${parsedSplitBuyerPct}% / ${100 - parsedSplitBuyerPct}%` });
      } else if (action === "arbitration") {
        await arb.mutateAsync({ dealId: deal.id, body: { reason: reason || undefined } });
        toast.show({ kind: "success", title: "Арбитраж открыт" });
      } else if (action === "assign") {
        if (!arbiterUsername.trim()) {
          toast.show({ kind: "error", title: "Введите username арбитра" });
          return;
        }
        // Lookup user by username. Uses the OpenAPI-generated
        // ``AdminUserListDto`` instead of ``any`` so a field rename
        // on the backend trips ``tsc`` instead of surfacing at
        // runtime as ``Cannot read properties of undefined``.
        const u: AdminUserListDto = await api
          .get(`api/admin/users`, {
            searchParams: { q: arbiterUsername.trim(), page: "1", page_size: "1" },
          })
          .json();
        const needle = arbiterUsername.trim().toLowerCase().replace(/^@/, "");
        const candidate = u.items.find(
          (x) => x.username?.toLowerCase() === needle,
        );
        if (!candidate) {
          toast.show({ kind: "error", title: "Юзер не найден" });
          return;
        }
        if (!candidate.is_arbiter) {
          toast.show({ kind: "error", title: "Этот юзер не арбитр" });
          return;
        }
        await assign.mutateAsync({
          dealId: deal.id,
          body: { arbiter_id: candidate.id },
        });
        toast.show({ kind: "success", title: "Арбитр назначен" });
      } else if (action === "delete") {
        await del.mutateAsync({ dealId: deal.id, body: { reason: reason || undefined } });
        toast.show({ kind: "success", title: "Сделка удалена, средства возвращены" });
        navigate("/admin/deals", { replace: true });
      }
      setSheet(null);
      setReason("");
      setApprovalId("");
    } catch (e: unknown) {
      toast.show({ kind: "error", title: "Ошибка", body: (e as Error)?.message ?? "" });
    }
  };

  const buttons = [
    {
      key: "release" as const,
      label: "Принудительное завершение",
      icon: Check,
      variant: "primary" as const,
      disabled: terminal,
    },
    {
      key: "refund" as const,
      label: "Возврат покупателю",
      icon: Undo2,
      variant: "secondary" as const,
      disabled: terminal,
    },
    {
      key: "split" as const,
      label: "Сплит-выплата",
      icon: Split,
      variant: "secondary" as const,
      disabled: terminal,
    },
    {
      key: "arbitration" as const,
      label: "Открыть арбитраж",
      icon: Gavel,
      variant: "secondary" as const,
      disabled: deal.status === "arbitration" || terminal,
    },
    {
      key: "assign" as const,
      label: "Назначить арбитра",
      icon: UserCheck,
      variant: "secondary" as const,
      disabled: deal.status !== "arbitration",
    },
    {
      key: "delete" as const,
      label: "Удалить сделку",
      icon: Trash2,
      variant: "danger" as const,
      disabled: false,
    },
  ];

  return (
    <section className="bg-panel rounded-card p-4 space-y-2">
      <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wide mb-1">Действия</h3>
      {approvals.length > 0 && (
        <div className="rounded-card border border-border bg-panel-2 p-3 space-y-2">
          <div className="text-xs uppercase tracking-wide text-text-muted">Approvals</div>
          {approvals.map((a) => (
            <div key={a.id} className="flex items-center gap-2 text-xs">
              <div className="flex-1 min-w-0">
                <div className="font-medium truncate">#{a.id} · {a.action} · {a.status}</div>
                <div className="text-text-muted truncate">
                  {a.amount ?? "?"} {a.currency_code ?? ""}
                  {a.amount_usd_estimate ? ` · ~$${a.amount_usd_estimate}` : ""}
                </div>
              </div>
              {a.status === "pending" && (
                <>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={a.requested_by_id === currentAdminId || approve.isPending}
                    onClick={async () => {
                      try {
                        await approve.mutateAsync(a.id);
                        toast.show({ kind: "success", title: "Approved" });
                      } catch (e) {
                        toast.show({ kind: "error", title: "Error", body: (e as Error).message });
                      }
                    }}
                  >
                    OK
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={reject.isPending}
                    onClick={async () => {
                      try {
                        await reject.mutateAsync(a.id);
                        toast.show({ kind: "success", title: "Rejected" });
                      } catch (e) {
                        toast.show({ kind: "error", title: "Error", body: (e as Error).message });
                      }
                    }}
                  >
                    Reject
                  </Button>
                </>
              )}
            </div>
          ))}
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        {buttons.map((btn, _idx) => (
          <div
            key={btn.key}
          >
            <Button
              size="sm"
              fullWidth
              variant={btn.variant}
              disabled={btn.disabled}
              onClick={() => setSheet(btn.key)}
            >
              <btn.icon size={14} className="-ml-0.5" />
              <span className="ml-1.5">{btn.label}</span>
            </Button>
          </div>
        ))}
      </div>

      <Sheet open={sheet !== null} onClose={() => setSheet(null)} title={sheet ? actionTitle(sheet) : ""}>
        <div className="space-y-3">
          {sheet === "split" && (
            <Input
              label="Доля покупателя, %"
              type="number"
              inputMode="numeric"
              value={splitBuyerPct}
              error={splitBuyerPctError}
              onChange={(e) => setSplitBuyerPct(e.target.value)}
            />
          )}
          {sheet === "assign" && (
            <Input
              label="Username арбитра"
              placeholder="@arbiter1"
              value={arbiterUsername}
              onChange={(e) => setArbiterUsername(e.target.value)}
            />
          )}
          {(sheet === "release" || sheet === "refund" || sheet === "split") && (
            <Input
              label="Approval ID"
              inputMode="numeric"
              value={approvalId}
              error={approvalIdError}
              placeholder={String(approvedApprovalId(sheet) ?? "auto")}
              onChange={(e) => setApprovalId(e.target.value)}
            />
          )}
          {sheet !== "assign" && (
            <Textarea
              label="Причина (опционально)"
              placeholder="Краткое объяснение для аудита и DM сторонам"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          )}
          <div className="flex gap-2">
            <Button variant="secondary" fullWidth onClick={() => setSheet(null)}>
              Отмена
            </Button>
            <Button
              fullWidth
              variant={sheet === "delete" ? "danger" : "primary"}
              onClick={() => sheet && run(sheet)}
            >
              Подтвердить
            </Button>
          </div>
        </div>
      </Sheet>
    </section>
  );
}

function actionTitle(a: "release" | "refund" | "split" | "arbitration" | "assign" | "delete") {
  return {
    release: "Завершить — продавцу",
    refund: "Возврат покупателю",
    split: "Сплит-выплата",
    arbitration: "Открыть арбитраж",
    assign: "Назначить арбитра",
    delete: "Удалить сделку",
  }[a];
}

// ── Timeline ─────────────────────────────────────────────────────────────

function EventsTimeline({ deal }: { deal: AdminDealDetailDto }) {
  if (deal.events.length === 0) return null;
  return (
    <section className="bg-panel rounded-card p-4">
      <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wide mb-2">События</h3>
      <ul className="space-y-2">
          {deal.events.map((ev, idx) => (
            <li
              key={`${ev.kind}-${ev.at}-${idx}`}
              className="flex items-start gap-2 text-sm"
            >
              <CornerDownRight size={14} className="text-text-muted mt-0.5 shrink-0" />
              <div className="flex-1">
                <div className="font-medium">{EVENT_KIND[ev.kind] ?? ev.kind}</div>
                <div className="text-xs text-text-muted">
                  {shortDate(ev.at)}
                  {ev.actor ? ` · ${ev.actor}` : ""} · {ev.description}
                </div>
              </div>
            </li>
          ))}
      </ul>
    </section>
  );
}

// ── Messages ─────────────────────────────────────────────────────────────

function MessagesFeed({ deal }: { deal: AdminDealDetailDto }) {
  const toast = useToast();
  const { data: messages, isLoading } = useDealMessages(deal.id);
  const loadOlder = useLoadOlderDealMessages(deal.id);
  const sendMessage = useSendDealMessage(deal.id);
  const [text, setText] = useState("");
  const [reachedOldest, setReachedOldest] = useState(false);

  useEffect(() => {
    setReachedOldest(false);
  }, [deal.id]);

  const items = messages ?? [];
  const canLoadOlder = !reachedOldest && items.length >= DEAL_MESSAGE_PAGE_SIZE;

  const onLoadOlder = async () => {
    if (!items.length || loadOlder.isPending) return;
    try {
      const page = await loadOlder.mutateAsync({ beforeId: items[0].id });
      if (page.length < DEAL_MESSAGE_PAGE_SIZE) {
        setReachedOldest(true);
      }
    } catch (e: unknown) {
      toast.show({
        kind: "error",
        title: "Не удалось загрузить историю",
        body: (e as Error)?.message ?? "",
      });
    }
  };

  const send = async () => {
    const t = text.trim();
    if (!t) return;
    try {
      await sendMessage.mutateAsync({ text: t, attachments: [] });
      toast.show({ kind: "success", title: "Сообщение отправлено" });
      setText("");
      // Refresh the page-level query
      window.dispatchEvent(new CustomEvent("admin-deal-refetch"));
    } catch (e: unknown) {
      toast.show({ kind: "error", title: "Не отправлено", body: (e as Error)?.message ?? "" });
    }
  };

  return (
    <section className="bg-panel rounded-card p-4">
      <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wide mb-2">Чат сделки</h3>
      {isLoading ? (
        <Skeleton className="h-16 mb-3" />
      ) : items.length === 0 ? (
        <div className="text-sm text-text-muted py-4 text-center">Пока пусто</div>
      ) : (
        <ul className="space-y-2 mb-3">
          {canLoadOlder && (
            <li className="flex justify-center pb-1">
              <button
                type="button"
                onClick={onLoadOlder}
                disabled={loadOlder.isPending}
                className="text-xs text-text-muted hover:text-text disabled:opacity-50 underline-offset-2 hover:underline"
              >
                {loadOlder.isPending ? "Загружаю..." : "Показать более ранние"}
              </button>
            </li>
          )}
          {items.map((m) => {
            const isBuyer = m.sender_id === deal.buyer.user_id;
            const isSeller = m.sender_id === deal.seller.user_id;
            const side = isBuyer ? "buyer" : isSeller ? "seller" : "staff";
            return (
              <li
                key={m.id}
                className={`rounded-card p-2 text-sm ${
                  side === "buyer"
                    ? "bg-panel-2"
                    : side === "seller"
                    ? "bg-panel-2"
                    : "bg-accent/10 border border-accent/30"
                }`}
              >
                <div className="text-[11px] uppercase tracking-wide text-text-muted mb-0.5">
                  {side === "staff" ? "Админ/арбитр" : side === "buyer" ? "Покупатель" : "Продавец"} · {formatAdminUsername(m.sender_username)} · {shortDate(m.created_at)}
                </div>
                <div className="whitespace-pre-wrap">{m.text}</div>
              </li>
            );
          })}
        </ul>
      )}
      <div className="flex items-end gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={2}
          placeholder="Сообщение в чат сделки от админа"
          className="flex-1 bg-panel-2 rounded-button px-3 py-2 text-sm placeholder:text-text-muted focus:outline-none resize-y"
        />
        <Button onClick={send} disabled={sendMessage.isPending || !text.trim()}>
          <Send size={14} />
        </Button>
      </div>
    </section>
  );
}

function shortDate(value: string): string {
  return formatDateTime(value, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
