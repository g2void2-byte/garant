import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type User } from "@/api";
import { Avatar, Money } from "@/components/ui";
import { notify } from "@/telegram";

export default function Users() {
  const [q, setQ] = useState("");
  const qc = useQueryClient();
  const { data: users = [] } = useQuery({
    queryKey: ["admin-users", q],
    queryFn: () => api.admin.listUsers(q),
  });

  return (
    <div className="space-y-3">
      <input
        className="input"
        placeholder="Поиск по @username, имени"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {users.map((u) => (
        <UserRow key={u.id} user={u} onChange={() => qc.invalidateQueries({ queryKey: ["admin-users"] })} />
      ))}
      {users.length === 0 && (
        <div className="glass-card p-6 text-center text-white/50">
          Ничего не нашли
        </div>
      )}
    </div>
  );
}

function UserRow({ user, onChange }: { user: User; onChange: () => void }) {
  const [delta, setDelta] = useState("");
  const update = useMutation({
    mutationFn: (body: Parameters<typeof api.admin.updateUser>[1]) =>
      api.admin.updateUser(user.id, body),
    onSuccess: () => {
      notify("success");
      onChange();
    },
    onError: (e) => alert((e as Error).message),
  });

  return (
    <div className="glass-card p-4">
      <div className="flex items-center gap-3">
        <Avatar
          url={user.photo_url}
          name={`${user.first_name ?? ""} ${user.last_name ?? ""}`}
        />
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold">
            {user.first_name} {user.last_name}
          </div>
          <div className="truncate text-xs text-white/55">
            {user.username ? `@${user.username}` : `id ${user.tg_id}`}
            {user.is_admin && (
              <span className="ml-2 rounded-md bg-brand/15 px-1.5 text-[10px] font-semibold uppercase text-brand-300">
                admin
              </span>
            )}
            {user.is_banned && (
              <span className="ml-2 rounded-md bg-rose-500/15 px-1.5 text-[10px] font-semibold uppercase text-rose-300">
                banned
              </span>
            )}
          </div>
        </div>
        <div className="text-right text-xs text-white/60">
          <div>
            Баланс <span className="font-semibold text-white"><Money value={user.balance} /></span>
          </div>
          <div>
            Эскроу <span className="font-semibold text-white"><Money value={user.frozen} /></span>
          </div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <div className="col-span-2 flex gap-2">
          <input
            inputMode="decimal"
            className="input flex-1"
            placeholder="±сумма $"
            value={delta}
            onChange={(e) => setDelta(e.target.value.replace(",", "."))}
          />
          <button
            disabled={!delta || update.isPending}
            onClick={() => {
              update.mutate({ balance_delta: Number(delta), note: "Admin adjust" });
              setDelta("");
            }}
            className="btn-primary"
          >
            Применить
          </button>
        </div>
        <button
          onClick={() => update.mutate({ is_banned: !user.is_banned })}
          className={user.is_banned ? "btn-ghost" : "btn-danger"}
        >
          {user.is_banned ? "Разбанить" : "Забанить"}
        </button>
        <button
          onClick={() => update.mutate({ is_admin: !user.is_admin })}
          className="btn-ghost"
        >
          {user.is_admin ? "Снять админа" : "Сделать админом"}
        </button>
      </div>
    </div>
  );
}
