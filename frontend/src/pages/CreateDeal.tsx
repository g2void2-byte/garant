import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";

import { api, type UserShort } from "@/api";
import { Avatar, GradientText, Money } from "@/components/ui";
import { useUser } from "@/store";
import { haptic, notify } from "@/telegram";

export default function CreateDeal() {
  const navigate = useNavigate();
  const { refresh } = useUser();
  const [params] = useSearchParams();

  const [role, setRole] = useState<"buyer" | "seller">("buyer");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState<string>("");
  const [counterpartyQuery, setCounterpartyQuery] = useState("");
  const [counterparty, setCounterparty] = useState<UserShort | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: searchResults = [] } = useQuery({
    queryKey: ["users", counterpartyQuery],
    queryFn: () => api.searchUsers(counterpartyQuery),
    enabled: counterpartyQuery.length >= 1 && !counterparty,
  });

  // Allow ?counterparty=<tg_id> deep link from the Home search panel
  useEffect(() => {
    const tgId = params.get("counterparty");
    if (!tgId) return;
    api.getUser(Number(tgId)).then(setCounterparty).catch(() => {});
  }, [params]);

  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: api.settings,
  });

  const submit = useMutation({
    mutationFn: () =>
      api.createDeal({
        title,
        description,
        amount: Number(amount),
        role,
        counterparty_tg_id: counterparty?.tg_id,
      }),
    onSuccess: async (deal) => {
      notify("success");
      await refresh();
      navigate(`/deals/${deal.id}`);
    },
    onError: (e) => {
      notify("error");
      setError((e as Error).message);
    },
  });

  const amountNum = Number(amount) || 0;
  const commission = settings
    ? Math.round((amountNum * settings.commission_percent) / 100 * 100) / 100
    : 0;

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

      <h1 className="text-2xl font-bold">
        <GradientText>Новая сделка</GradientText>
      </h1>

      <section className="glass-card flex flex-col gap-4 p-5">
        <div className="grid grid-cols-2 gap-2">
          <RoleButton active={role === "buyer"} onClick={() => setRole("buyer")}>
            🛒 Я покупатель
          </RoleButton>
          <RoleButton active={role === "seller"} onClick={() => setRole("seller")}>
            🏷 Я продавец
          </RoleButton>
        </div>

        <Field label="Контрагент">
          {counterparty ? (
            <div className="flex items-center gap-3 rounded-2xl bg-bg/40 p-3">
              <Avatar
                url={counterparty.photo_url}
                name={`${counterparty.first_name ?? ""} ${counterparty.last_name ?? ""}`}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold">
                  {counterparty.first_name} {counterparty.last_name}
                </div>
                <div className="truncate text-xs text-white/50">
                  {counterparty.username
                    ? `@${counterparty.username}`
                    : `id ${counterparty.tg_id}`}
                </div>
              </div>
              <button
                onClick={() => setCounterparty(null)}
                className="text-xs text-white/50 hover:text-white"
              >
                ✕
              </button>
            </div>
          ) : (
            <>
              <input
                className="input"
                placeholder="@username, имя или Telegram ID"
                value={counterpartyQuery}
                onChange={(e) => setCounterpartyQuery(e.target.value)}
              />
              {searchResults.length > 0 && (
                <div className="mt-2 space-y-1 rounded-2xl bg-bg/40 p-2">
                  {searchResults.slice(0, 6).map((u) => (
                    <button
                      key={u.id}
                      onClick={() => {
                        setCounterparty(u);
                        setCounterpartyQuery("");
                        haptic();
                      }}
                      className="flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left hover:bg-white/5"
                    >
                      <Avatar
                        url={u.photo_url}
                        name={`${u.first_name ?? ""} ${u.last_name ?? ""}`}
                        size={32}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm">
                          {u.first_name} {u.last_name}
                        </div>
                        <div className="truncate text-xs text-white/45">
                          {u.username ? `@${u.username}` : `id ${u.tg_id}`}
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
        </Field>

        <Field label="Название сделки">
          <input
            className="input"
            placeholder="Например, MacBook Pro 14"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </Field>

        <Field label="Описание (необязательно)">
          <textarea
            className="input min-h-[80px] resize-none"
            placeholder="Условия, сроки, что входит в сделку…"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>

        <Field label="Сумма, $">
          <input
            inputMode="decimal"
            className="input text-lg font-semibold"
            placeholder="0.00"
            value={amount}
            onChange={(e) => setAmount(e.target.value.replace(",", "."))}
          />
        </Field>

        {settings && (
          <div className="flex items-center justify-between rounded-2xl bg-bg/40 p-3 text-sm">
            <div className="text-white/60">
              Комиссия сервиса · {settings.commission_percent}%
            </div>
            <div className="font-semibold text-brand">
              <Money value={commission} />
            </div>
          </div>
        )}

        {error && (
          <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-300">
            {error}
          </div>
        )}

        <button
          disabled={
            !title ||
            !amount ||
            !counterparty ||
            submit.isPending
          }
          onClick={() => submit.mutate()}
          className="btn-primary mt-1 disabled:opacity-50"
        >
          🚀 Создать сделку
        </button>
      </section>
    </motion.div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <div className="mb-1 text-xs uppercase tracking-wide text-white/45">
        {label}
      </div>
      {children}
    </label>
  );
}

function RoleButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-2xl px-4 py-3 text-sm font-semibold transition ${
        active
          ? "bg-gradient-to-br from-brand-200 via-brand-400 to-brand-500 text-bg shadow-glow"
          : "bg-bg/40 text-white/70 hover:text-white"
      }`}
    >
      {children}
    </button>
  );
}
