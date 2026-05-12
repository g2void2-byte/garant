import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";

import { api } from "@/api";
import { Money } from "@/components/ui";
import { useUser } from "@/store";
import { notify } from "@/telegram";

export default function Balance() {
  const { user, setUser } = useUser();
  const qc = useQueryClient();
  const [tab, setTab] = useState<"deposit" | "withdraw">("deposit");
  const [amount, setAmount] = useState("");

  const { data: txs = [] } = useQuery({
    queryKey: ["txs"],
    queryFn: api.transactions,
  });

  const mutate = useMutation({
    mutationFn: () =>
      tab === "deposit"
        ? api.deposit(Number(amount), "Demo deposit")
        : api.withdraw(Number(amount), "Demo withdraw"),
    onSuccess: (u) => {
      notify("success");
      setUser(u);
      setAmount("");
      qc.invalidateQueries({ queryKey: ["txs"] });
    },
    onError: (e) => {
      notify("error");
      alert((e as Error).message);
    },
  });

  if (!user) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col gap-4 px-4 pt-8"
    >
      <h1 className="text-2xl font-bold">Баланс</h1>

      <section className="glass-card p-5">
        <div className="text-xs uppercase tracking-wide text-white/45">
          Доступно
        </div>
        <div className="mt-1 text-4xl font-extrabold text-brand">
          <Money value={user.balance} />
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
          <Cell label="Заморожено в эскроу" value={user.frozen} />
          <Cell label="Страховой депозит" value={user.insurance} />
        </div>
      </section>

      <section className="glass-card p-5">
        <div className="mb-4 grid grid-cols-2 gap-2">
          <Tab active={tab === "deposit"} onClick={() => setTab("deposit")}>
            ⬇ Пополнить
          </Tab>
          <Tab active={tab === "withdraw"} onClick={() => setTab("withdraw")}>
            ⬆ Вывести
          </Tab>
        </div>
        <div className="space-y-3">
          <input
            inputMode="decimal"
            className="input text-lg"
            placeholder="0.00"
            value={amount}
            onChange={(e) => setAmount(e.target.value.replace(",", "."))}
          />
          <div className="flex flex-wrap gap-2">
            {[10, 50, 100, 500, 1000].map((v) => (
              <button
                key={v}
                onClick={() => setAmount(String(v))}
                className="pill bg-bg/40 text-white/70 hover:bg-bg/60"
              >
                +${v}
              </button>
            ))}
          </div>
          <button
            disabled={!amount || Number(amount) <= 0 || mutate.isPending}
            onClick={() => mutate.mutate()}
            className="btn-primary w-full disabled:opacity-50"
          >
            {tab === "deposit" ? "💳 Пополнить" : "💸 Вывести"}
          </button>
          <p className="text-center text-xs text-white/40">
            * демо-режим: пополнение и вывод имитируются без платёжного провайдера
          </p>
        </div>
      </section>

      <section className="glass-card p-5">
        <h2 className="mb-3 text-lg font-semibold">История</h2>
        <div className="space-y-2">
          {txs.length === 0 && (
            <div className="rounded-2xl bg-bg/30 p-4 text-center text-sm text-white/40">
              Здесь будут операции по балансу.
            </div>
          )}
          {txs.map((t) => (
            <div
              key={t.id}
              className="flex items-center justify-between rounded-2xl bg-bg/40 p-3 text-sm"
            >
              <div>
                <div className="font-medium capitalize">{translateTx(t.type)}</div>
                <div className="text-xs text-white/45">
                  {new Date(t.created_at).toLocaleString()}
                  {t.note ? ` · ${t.note}` : ""}
                </div>
              </div>
              <div
                className={`font-semibold ${
                  t.type === "withdraw" || t.type === "commission" || t.type === "hold"
                    ? "text-rose-300"
                    : "text-emerald-300"
                }`}
              >
                <Money value={t.amount} />
              </div>
            </div>
          ))}
        </div>
      </section>
    </motion.div>
  );
}

function Cell({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl bg-bg/40 p-3">
      <div className="text-xs uppercase tracking-wide text-white/45">{label}</div>
      <div className="mt-1 text-xl font-bold">
        <Money value={value} />
      </div>
    </div>
  );
}

function Tab({
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
      className={`rounded-full py-2 text-sm font-semibold transition ${
        active
          ? "bg-brand text-bg shadow-glow"
          : "bg-bg/40 text-white/70 hover:text-white"
      }`}
    >
      {children}
    </button>
  );
}

function translateTx(t: string): string {
  return (
    {
      deposit: "Пополнение",
      withdraw: "Вывод",
      hold: "Заморозка в эскроу",
      release: "Высвобождение из эскроу",
      refund: "Возврат",
      commission: "Комиссия сервиса",
      insurance_lock: "Страх. депозит — внесён",
      insurance_unlock: "Страх. депозит — возвращён",
      admin_adjust: "Коррекция администратором",
    }[t] ?? t
  );
}
