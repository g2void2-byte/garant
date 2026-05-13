import { useNavigate } from "react-router-dom";
import { useRef, useState } from "react";
import {
  ArrowRightLeft,
  Image as ImageIcon,
  Pause,
  Play,
  Plus,
  Trash2,
  Upload,
  Wallet,
  Settings as SettingsIcon,
  Star,
  Link2,
} from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Button } from "@/components/ui/Button";
import { ToggleTabs } from "@/components/ui/ToggleTabs";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Sheet } from "@/components/ui/Sheet";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { ProfileHeader } from "@/components/domain/ProfileHeader";
import { ProfileStatsGrid } from "@/components/domain/ProfileStatsGrid";
import { ServiceCard } from "@/components/domain/ServiceCard";
import {
  useDeleteService,
  useMe,
  useReviews,
  useServices,
  useUpdateMe,
  useUpdateService,
  useUploadMedia,
} from "@/api/hooks";
import { haptic } from "@/lib/tg";
import { relativeTime } from "@/lib/format";

export default function ProfilePage() {
  const navigate = useNavigate();
  const { data: me, isLoading } = useMe();
  const [tab, setTab] = useState<"services" | "reviews">("services");
  const { data: services } = useServices({ owner: me?.username });
  const { data: reviews } = useReviews(me?.username);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [forumsOpen, setForumsOpen] = useState(false);

  const updateMe = useUpdateMe();
  const updateService = useUpdateService();
  const deleteService = useDeleteService();
  const uploadMedia = useUploadMedia();
  const avatarFileRef = useRef<HTMLInputElement | null>(null);
  const bannerFileRef = useRef<HTMLInputElement | null>(null);

  const [description, setDescription] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [bannerUrl, setBannerUrl] = useState("");
  const [profileError, setProfileError] = useState<string | null>(null);
  const [forumName, setForumName] = useState("");
  const [forumUrl, setForumUrl] = useState("");
  const [forumsError, setForumsError] = useState<string | null>(null);

  if (isLoading || !me) {
    return (
      <Page>
        <div className="px-4 space-y-3 pt-3">
          <Skeleton className="h-64" />
          <Skeleton className="h-32" />
        </div>
      </Page>
    );
  }

  const openSettings = () => {
    setDescription(me.description || "");
    setDisplayName(me.display_name || "");
    setBannerUrl(me.banner_url || "");
    setProfileError(null);
    setSettingsOpen(true);
  };

  const extractApiError = async (e: unknown): Promise<string> => {
    const ke = e as { response?: Response; message?: string };
    try {
      const data = await ke.response?.json();
      if (Array.isArray(data?.detail)) {
        return data.detail.map((d: { msg?: string }) => d.msg ?? "").filter(Boolean).join("\n");
      }
      if (typeof data?.detail === "string") return data.detail;
    } catch {
      /* fall through */
    }
    return ke.message || "Не удалось сохранить";
  };

  const saveSettings = async () => {
    setProfileError(null);
    try {
      await updateMe.mutateAsync({
        description,
        display_name: displayName,
        banner_url: bannerUrl ? bannerUrl : null,
      });
      haptic("success");
      setSettingsOpen(false);
    } catch (e) {
      haptic("error");
      setProfileError(await extractApiError(e));
    }
  };

  const addForum = async () => {
    setForumsError(null);
    const forums = [...(me.forums || [])];
    forums.push({ name: forumName, url: forumUrl });
    try {
      await updateMe.mutateAsync({ forums });
      setForumName("");
      setForumUrl("");
      haptic("success");
    } catch (e) {
      haptic("error");
      setForumsError(await extractApiError(e));
    }
  };

  const onPickImage = (kind: "avatar" | "banner") => async (
    e: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const uploaded = await uploadMedia.mutateAsync({ kind, file });
      if (kind === "avatar") {
        setProfileError(null);
        await updateMe.mutateAsync({ photo_url: uploaded.url });
      } else {
        setBannerUrl(uploaded.url);
        await updateMe.mutateAsync({ banner_url: uploaded.url });
      }
      haptic("success");
    } catch (err) {
      haptic("error");
      setProfileError(await extractApiError(err));
    }
  };

  const removeForum = async (idx: number) => {
    const forums = (me.forums || []).filter((_, i) => i !== idx);
    try {
      await updateMe.mutateAsync({ forums });
      haptic("success");
    } catch (e) {
      haptic("error");
      setForumsError(await extractApiError(e));
    }
  };

  return (
    <Page>
      <ProfileHeader user={me} />

      <div className="px-4 mt-3 space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <Button variant="primary" onClick={() => navigate("/profile/services/new")}>
            <Plus className="size-4" /> Добавить услугу
          </Button>
          <Button variant="primary" onClick={() => navigate("/wallet")}>
            <Wallet className="size-4" /> Депозит
          </Button>
          <Button variant="secondary" onClick={openSettings}>
            <SettingsIcon className="size-4" /> Настройки
          </Button>
          <Button variant="secondary" onClick={() => setForumsOpen(true)}>
            <Link2 className="size-4" /> Добавить форумы
          </Button>
        </div>

        <ProfileStatsGrid user={me} onDepositClick={() => navigate("/wallet")} />

        <ToggleTabs
          value={tab}
          options={[
            { value: "services", label: "Услуги", count: services?.length ?? 0 },
            { value: "reviews", label: "Отзывы", count: reviews?.length ?? 0 },
          ]}
          onChange={setTab}
          layoutId="profile-self-tabs"
        />

        {tab === "services" &&
          (!services || services.length === 0 ? (
            <EmptyState title="Услуги отсутствуют" description="Нажмите «Добавить услугу», чтобы добавить первую" />
          ) : (
            services.map((s, i) => (
              <ServiceCard
                key={s.id}
                service={s}
                index={i}
                rightSlot={
                  <div className="flex flex-col items-end gap-1 shrink-0">
                    {s.status !== "banned" && (
                      <button
                        type="button"
                        className="size-8 grid place-items-center rounded-full bg-panel-2 text-text-muted active:scale-95"
                        aria-label={s.status === "active" ? "Поставить на паузу" : "Сделать активной"}
                        onClick={() => {
                          haptic("light");
                          updateService.mutate({
                            id: s.id,
                            body: { status: s.status === "active" ? "paused" : "active" },
                          });
                        }}
                      >
                        {s.status === "active" ? (
                          <Pause className="size-4" />
                        ) : (
                          <Play className="size-4" />
                        )}
                      </button>
                    )}
                    <button
                      type="button"
                      className="size-8 grid place-items-center rounded-full bg-panel-2 text-danger active:scale-95"
                      aria-label="Удалить"
                      onClick={() => {
                        if (window.confirm(`Удалить услугу «${s.title}»?`)) {
                          haptic("warning");
                          deleteService.mutate(s.id);
                        }
                      }}
                    >
                      <Trash2 className="size-4" />
                    </button>
                  </div>
                }
              />
            ))
          ))}

        {tab === "reviews" &&
          (!reviews || reviews.length === 0 ? (
            <EmptyState
              icon={<Star className="size-5" />}
              title="Отзывов нет"
              description="Завершайте сделки, чтобы получить отзывы"
            />
          ) : (
            reviews.map((r) => (
              <div key={r.id} className="bg-panel border border-border rounded-card p-3">
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-accent font-bold">★ {r.rating.toFixed(1)}</span>
                  <span className="text-text-muted">от @{r.author_username}</span>
                  <span className="text-text-muted ml-auto">{relativeTime(r.created_at)}</span>
                </div>
                {r.text && <div className="mt-2 text-sm">{r.text}</div>}
              </div>
            ))
          ))}
      </div>

      <Sheet open={settingsOpen} onClose={() => setSettingsOpen(false)} title="Настройки">
        <div className="space-y-3">
          <input
            ref={avatarFileRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            className="hidden"
            onChange={onPickImage("avatar")}
          />
          <input
            ref={bannerFileRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            className="hidden"
            onChange={onPickImage("banner")}
          />
          <div className="grid grid-cols-2 gap-2">
            <Button
              variant="secondary"
              onClick={() => avatarFileRef.current?.click()}
              disabled={uploadMedia.isPending}
            >
              <Upload className="size-4" /> Аватар
            </Button>
            <Button
              variant="secondary"
              onClick={() => bannerFileRef.current?.click()}
              disabled={uploadMedia.isPending}
            >
              <ImageIcon className="size-4" /> Баннер
            </Button>
          </div>
          <Input
            label="Никнейм"
            placeholder="Отображаемое имя"
            value={displayName}
            maxLength={64}
            onChange={(e) => setDisplayName(e.target.value)}
          />
          <Textarea
            label="Описание профиля"
            placeholder="Расскажите о себе"
            value={description}
            maxLength={1024}
            onChange={(e) => setDescription(e.target.value)}
          />
          <Input
            label="Баннер (URL)"
            placeholder="https://..."
            value={bannerUrl}
            inputMode="url"
            onChange={(e) => setBannerUrl(e.target.value)}
          />
          {profileError && (
            <div className="text-sm text-danger whitespace-pre-line">{profileError}</div>
          )}
          <Button fullWidth onClick={saveSettings} disabled={updateMe.isPending}>
            Сохранить
          </Button>
          <Button
            fullWidth
            variant="secondary"
            onClick={() => {
              setSettingsOpen(false);
              navigate("/profile/transfer");
            }}
          >
            <ArrowRightLeft className="size-4" />
            Перенести аккаунт
          </Button>
        </div>
      </Sheet>

      <Sheet open={forumsOpen} onClose={() => setForumsOpen(false)} title="Форумы">
        <div className="space-y-3">
          {me.forums?.map((f, i) => (
            <div
              key={i}
              className="bg-panel-2 rounded-2xl p-3 text-sm flex items-start justify-between gap-2"
            >
              <div className="min-w-0">
                <div className="font-semibold truncate">{f.name || "—"}</div>
                <div className="text-text-muted truncate">{f.url}</div>
              </div>
              <button
                type="button"
                aria-label="Удалить"
                onClick={() => removeForum(i)}
                className="text-text-muted active:scale-95"
              >
                <Trash2 className="size-4" />
              </button>
            </div>
          ))}
          <Input
            label="Название"
            value={forumName}
            maxLength={64}
            onChange={(e) => setForumName(e.target.value)}
          />
          <Input
            label="Ссылка"
            placeholder="https://..."
            inputMode="url"
            value={forumUrl}
            onChange={(e) => setForumUrl(e.target.value)}
          />
          {forumsError && (
            <div className="text-sm text-danger whitespace-pre-line">{forumsError}</div>
          )}
          <Button fullWidth onClick={addForum} disabled={!forumName || !forumUrl}>
            Добавить
          </Button>
        </div>
      </Sheet>
    </Page>
  );
}
