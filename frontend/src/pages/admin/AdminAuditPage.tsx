import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { History, Filter } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Skeleton } from "@/components/ui/Skeleton";
import { Input } from "@/components/ui/Input";
import { useAdminAuditLog } from "@/api/admin/hooks";
import type { AdminAuditLogDto } from "@/api/types";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";

export default function AdminAuditPage() {
  const navigate = useNavigate();
  const [action, setAction] = useState("");
  const [actorId, setActorId] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [page, setPage] = useState(1);
  const { data, isLoading } = useAdminAuditLog({
    action: action.trim() || undefined,
    actor_id: actorId ? Number(actorId) : undefined,
    page,
    page_size: 50,
  });

  const __guard = useAdminRedirect();
  if (!__guard.shouldRender) return null;

  return (
    <Page showBack onBack={() => navigate("/admin")}>
      <Header
        title="Аудит"
        subtitle={data ? `${data.total} событий` : undefined}
        right={
          <button
            type="button"
            onClick={() => setShowFilters((v) => !v)}
            className="rounded-button bg-panel p-2 text-text-muted active:scale-95"
          >
            <Filter size={18} />
          </button>
        }
      />
      {showFilters && (
        <motion.div
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          className="px-4 mb-3 space-y-2"
        >
          <Input
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setPage(1);
            }}
            placeholder="action (e.g. user.ban, deal.refund)"
          />
          <Input
            inputMode="numeric"
            value={actorId}
            onChange={(e) => {
              setActorId(e.target.value);
              setPage(1);
            }}
            placeholder="actor_id"
          />
        </motion.div>
      )}
      <div className="px-4 space-y-2 pb-24">
        {isLoading ? (
          Array.from({ length: 10 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-card" />
          ))
        ) : data?.items.length === 0 ? (
          <p className="text-sm text-text-muted text-center py-12">
            Событий не найдено
          </p>
        ) : (
          data?.items.map((row, idx) => (
            <motion.div
              key={row.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.01 }}
              className="bg-panel rounded-card p-3 text-sm"
            >
              <div className="flex items-baseline justify-between">
                <div className="font-mono text-xs text-accent">{row.action}</div>
                <div className="text-[11px] text-text-muted">
                  {new Date(row.created_at).toLocaleString()}
                </div>
              </div>
              <div className="text-xs text-text-muted mt-1">
                <span>by @{row.actor_username ?? row.actor_id ?? "system"}</span>
                {row.target_type && row.target_id != null && (
                  <span>
                    {" "}· target: {row.target_type}#{row.target_id}
                  </span>
                )}
                {row.ip && <span> · {row.ip}</span>}
              </div>
              {row.reason && (
                <div className="text-xs italic mt-1 text-text-muted">
                  Причина: {row.reason}
                </div>
              )}
              {row.payload && Object.keys(row.payload).length > 0 && (
                <PayloadPreview payload={row.payload} />
              )}
            </motion.div>
          ))
        )}
      </div>
      {data && data.total > data.page_size && (
        <div className="flex items-center justify-center gap-2 mt-2 px-4 pb-4">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="rounded-button bg-panel px-3 py-1.5 text-sm disabled:opacity-40"
          >
            <History size={12} className="inline mr-1" /> Назад
          </button>
          <span className="text-xs text-text-muted">
            {page} / {Math.ceil(data.total / data.page_size)}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => p + 1)}
            disabled={page * data.page_size >= data.total}
            className="rounded-button bg-panel px-3 py-1.5 text-sm disabled:opacity-40"
          >
            Вперёд
          </button>
        </div>
      )}
    </Page>
  );
}

function PayloadPreview({ payload }: { payload: AdminAuditLogDto["payload"] }) {
  const text = JSON.stringify(payload, null, 1);
  return (
    <pre className="bg-panel-2 rounded-button px-2 py-1.5 mt-2 text-[10px] font-mono overflow-x-auto whitespace-pre-wrap">
      {text.length > 240 ? `${text.slice(0, 240)}...` : text}
    </pre>
  );
}
