import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";

import { api, type Deal } from "@/api";
import { Avatar, Money, StatusPill } from "@/components/ui";
import { useUser } from "@/store";
import { haptic, notify } from "@/telegram";

export default function DealDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { user, refresh } = useUser();

  const { data: deal, isLoading } = useQuery({
    queryKey: ["deal", id],
    queryFn: () => api.getDeal(Number(id)),
    enabled: !!id,
  });

  const act = useMutation({
    mutationFn: (action: "fund" | "confirm" | "cancel" | "open_dispute") =>
      api.dealAction(Number(id), action),
    onSuccess: async () => {
      notify("success");
      haptic("medium");
      await qc.invalidateQueries({ queryKey: ["deal", id] });
      await qc.invalidateQueries({ queryKey: ["deals"] });
      await refresh();
    },
    onError: (e) => {
      notify("error");
      alert((e as Error).message);
    },
  });

  if (isLoading || !deal) {
    return <div className="p-8 text-center text-white/50">Загрузка…</div>;
  }
  if (!user) return null;

  const isBuyer = deal.buyer.id === user.id;
  const isSeller = deal.seller.id === user.id;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col gap-4 px-4 pt-6"
    >
      <button
        onClick={() => navigate(-1)}
        className="self-start text-sm text-white/60 hover:text-white"
      >
        ← Назад
      </button>

      <div className="glass-card p-6">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h1 className="text-2xl font-bold leading-tight">{deal.title}</h1>
          <StatusPill status={deal.status} />
        </div>
        {deal.description && (
          <p className="text-sm text-white/65">{deal.description}</p>
        )}

        <div className="my-5 flex items-end justify-between rounded-2xl bg-bg/40 p-4">
          <div>
            <div className="text-xs uppercase tracking-wide text-white/45">Сумма</div>
            <div className="text-3xl font-extrabold text-brand">
              <Money value={deal.amount} />
            </div>
          </div>
          <div className="text-right text-xs text-white/50">
            Комиссия сервиса
            <div className="text-sm font-semibold text-white/80">
              <Money value={deal.commission} />
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <PartyCard label="Покупатель" user={deal.buyer} self={isBuyer} />
          <PartyCard label="Продавец" user={deal.seller} self={isSeller} />
        </div>

        {deal.dispute_reason && (
          <div className="mt-4 rounded-2xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm">
            <div className="mb-1 font-semibold text-rose-300">Причина спора</div>
            <div className="text-white/80">{deal.dispute_reason}</div>
          </div>
        )}
      </div>

      <Actions deal={deal} onAct={(a) => act.mutate(a)} busy={act.isPending} />
    </motion.div>
  );
}

function PartyCard({
  label,
  user,
  self,
}: {
  label: string;
  user: Deal["buyer"];
  self: boolean;
}) {
  return (
    <div className="rounded-2xl bg-bg/40 p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs uppercase tracking-wide text-white/45">{label}</div>
        {self && <span className="pill bg-brand/15 text-brand-300">Вы</span>}
      </div>
      <div className="flex items-center gap-2">
        <Avatar
          url={user.photo_url}
          name={`${user.first_name ?? ""} ${user.last_name ?? ""}`}
          size={36}
        />
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">
            {user.first_name ?? "—"} {user.last_name ?? ""}
          </div>
          <div className="truncate text-xs text-white/50">
            {user.username ? `@${user.username}` : `id ${user.tg_id}`}
          </div>
        </div>
      </div>
    </div>
  );
}

function Actions({
  deal,
  onAct,
  busy,
}: {
  deal: Deal;
  onAct: (a: "fund" | "confirm" | "cancel" | "open_dispute") => void;
  busy: boolean;
}) {
  const { user } = useUser();
  if (!user) return null;
  const isBuyer = deal.buyer.id === user.id;
  const buttons: { label: string; action: Parameters<typeof onAct>[0]; cls: string }[] = [];

  if (deal.status === "awaiting_payment") {
    if (isBuyer)
      buttons.push({
        label: `Оплатить ${(deal.amount + deal.commission).toFixed(2)}$`,
        action: "fund",
        cls: "btn-primary",
      });
    buttons.push({ label: "Отменить", action: "cancel", cls: "btn-ghost" });
  }
  if (deal.status === "funded") {
    if (isBuyer)
      buttons.push({
        label: "✅ Подтвердить получение",
        action: "confirm",
        cls: "btn-primary",
      });
    buttons.push({
      label: "🚩 Открыть спор",
      action: "open_dispute",
      cls: "btn-danger",
    });
  }
  if (buttons.length === 0) return null;

  return (
    <div className="glass-card flex flex-wrap gap-2 p-4">
      {buttons.map((b) => (
        <button
          key={b.action}
          disabled={busy}
          onClick={() => {
            if (b.action === "open_dispute") {
              const reason = prompt("Причина спора?");
              if (!reason) return;
              onAct("open_dispute");
              return;
            }
            onAct(b.action);
          }}
          className={`${b.cls} flex-1`}
        >
          {b.label}
        </button>
      ))}
    </div>
  );
}
