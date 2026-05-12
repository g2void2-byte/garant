import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api";
import { notify } from "@/telegram";

export default function Settings() {
  const qc = useQueryClient();
  const { data: settings } = useQuery({
    queryKey: ["admin-settings"],
    queryFn: api.admin.settings,
  });

  const [commission, setCommission] = useState("");
  const [insurance, setInsurance] = useState("");
  const [welcome, setWelcome] = useState("");

  useEffect(() => {
    if (!settings) return;
    setCommission(String(settings.commission_percent));
    setInsurance(String(settings.insurance_deposit));
    setWelcome(settings.welcome_message);
  }, [settings]);

  const save = useMutation({
    mutationFn: () =>
      api.admin.updateSettings({
        commission_percent: Number(commission),
        insurance_deposit: Number(insurance),
        welcome_message: welcome,
      }),
    onSuccess: () => {
      notify("success");
      qc.invalidateQueries({ queryKey: ["admin-settings"] });
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (e) => alert((e as Error).message),
  });

  if (!settings) return <div className="glass-card h-40 animate-pulse" />;

  return (
    <div className="space-y-3">
      <section className="glass-card flex flex-col gap-3 p-5">
        <h2 className="text-lg font-semibold">Параметры сервиса</h2>
        <Field label="Комиссия сервиса, %">
          <input
            inputMode="decimal"
            className="input"
            value={commission}
            onChange={(e) => setCommission(e.target.value.replace(",", "."))}
          />
        </Field>
        <Field label="Страховой депозит, $">
          <input
            inputMode="decimal"
            className="input"
            value={insurance}
            onChange={(e) => setInsurance(e.target.value.replace(",", "."))}
          />
        </Field>
      </section>

      <section className="glass-card flex flex-col gap-3 p-5">
        <h2 className="text-lg font-semibold">Приветственное сообщение бота</h2>
        <p className="text-xs text-white/45">
          Используйте плейсхолдер{" "}
          <code className="rounded bg-white/10 px-1">{"{commission}"}</code>{" "}
          для подстановки текущей комиссии.
        </p>
        <textarea
          className="input min-h-[180px] resize-none font-mono text-xs leading-relaxed"
          value={welcome}
          onChange={(e) => setWelcome(e.target.value)}
        />
      </section>

      <button
        onClick={() => save.mutate()}
        disabled={save.isPending}
        className="btn-primary w-full"
      >
        💾 Сохранить
      </button>
    </div>
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
