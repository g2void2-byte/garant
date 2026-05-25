import { useState } from "react";
import { Link2, Plus, Trash2 } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { useToast } from "@/components/ui/Toast";
import { useForums, useMe, useUpdateMe } from "@/api/hooks";
import { haptic } from "@/lib/tg";

/**
 * Continental "Добавление форума" page (photo 9 of 20).
 *
 * Layout:
 *   - "Добавленные" section: list of current forums with delete buttons.
 *   - "Добавить новый" section:
 *       · forum picker ("Выберите форум" dropdown)
 *       · URL input  ("Укажите ссылку на форум")
 *       · primary button "Добавить"
 *
 * Forum names are validated against a fixed list approved by the
 * backend (``backend.app.schemas.FORUM_WHITELIST``). Audit v3 A-1 —
 * the list is fetched from ``GET /api/forums`` so this component
 * cannot drift from the write-boundary validator on
 * ``ForumIn._name_in_whitelist``. The hard-coded fallback below is
 * only used if the network request fails (offline cold start) so the
 * dropdown still renders something usable.
 */
const FORUM_OPTIONS_FALLBACK = [
  "Carder.market",
  "DarkNet",
  "Darkmoney",
  "Korovka",
  "Lolzteam",
  "Maza",
  "Probiv",
  "Verified",
  "Другое",
];

export default function AddForumPage() {
  const { data: me, isLoading } = useMe();
  const { data: forumList } = useForums();
  const updateMe = useUpdateMe();
  const toast = useToast();

  const [forumName, setForumName] = useState<string>("");
  const [forumUrl, setForumUrl] = useState<string>("");

  const forumOptions = forumList?.forums ?? FORUM_OPTIONS_FALLBACK;

  const extractApiError = async (e: unknown): Promise<string> => {
    const ke = e as { response?: Response; message?: string };
    try {
      const data = await ke.response?.json();
      if (Array.isArray(data?.detail)) {
        return data.detail
          .map((d: { msg?: string }) => d.msg ?? "")
          .filter(Boolean)
          .join("\n");
      }
      if (typeof data?.detail === "string") return data.detail;
    } catch {
      /* fall through */
    }
    return ke.message || "Не удалось сохранить";
  };

  const addForum = async () => {
    if (!me) return;
    if (!forumName || !forumUrl.trim()) {
      haptic("error");
      toast.show({ kind: "error", title: "Заполните все поля" });
      return;
    }
    const forums = [...(me.forums || []), { name: forumName, url: forumUrl.trim() }];
    try {
      await updateMe.mutateAsync({ forums });
      haptic("success");
      setForumName("");
      setForumUrl("");
      toast.show({ kind: "success", title: "Форум добавлен" });
    } catch (e) {
      haptic("error");
      toast.show({ kind: "error", title: await extractApiError(e) });
    }
  };

  const removeForum = async (idx: number) => {
    if (!me) return;
    const forums = (me.forums || []).filter((_, i) => i !== idx);
    try {
      await updateMe.mutateAsync({ forums });
      haptic("success");
    } catch (e) {
      haptic("error");
      toast.show({ kind: "error", title: await extractApiError(e) });
    }
  };

  if (isLoading || !me) {
    return (
      <Page showBack>
        <Header title="Добавление форума" />
        <div className="px-4 space-y-2">
          <Skeleton className="h-16 w-full rounded-card" />
          <Skeleton className="h-12 w-full rounded-button" />
          <Skeleton className="h-12 w-full rounded-button" />
          <Skeleton className="h-11 w-full rounded-button" />
        </div>
      </Page>
    );
  }

  return (
    <Page showBack>
      <Header title="Добавление форума" />
      <div className="px-4 space-y-4">
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-text-muted px-1">Добавленные</h2>
          {me.forums?.length === 0 ? (
            <EmptyState title="Нет форумов" description="Добавьте ваш первый форум ниже" />
          ) : (
            me.forums?.map((f, i) => (
              <div
                key={`${f.name}-${i}`}
                className="bg-panel rounded-card p-3 flex items-start justify-between gap-2"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="size-9 grid place-items-center rounded-full bg-panel-2 text-accent shrink-0">
                    <Link2 className="size-4" />
                  </div>
                  <div className="min-w-0">
                    <div className="font-semibold truncate">{f.name}</div>
                    <div className="text-xs text-text-muted truncate">{f.url}</div>
                  </div>
                </div>
                <button
                  type="button"
                  aria-label={`Удалить форум ${f.name}`}
                  onClick={() => removeForum(i)}
                  className="size-9 grid place-items-center rounded-full bg-panel-2 text-danger active:scale-95 shrink-0"
                >
                  <Trash2 className="size-4" />
                </button>
              </div>
            ))
          )}
        </section>

        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-text-muted px-1">Добавить новый</h2>
          <div>
            <div className="mb-1 text-[14px] font-medium">Выберите форум</div>
            <Select
              value={forumName}
              options={forumOptions.map((o) => ({ value: o, label: o }))}
              onChange={setForumName}
              placeholder="Выберите форум"
              withIcon={false}
            />
          </div>
          <Input
            label="Укажите ссылку на форум"
            placeholder="Название-форума.com"
            value={forumUrl}
            inputMode="url"
            onChange={(e) => setForumUrl(e.target.value)}
          />
          <Button fullWidth onClick={addForum} disabled={updateMe.isPending}>
            <Plus className="size-4" /> Добавить
          </Button>
        </section>
      </div>
    </Page>
  );
}
