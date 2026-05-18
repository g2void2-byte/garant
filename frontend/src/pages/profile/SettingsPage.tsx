import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRightLeft,
  EyeOff,
  Image as ImageIcon,
  Bell,
  KeyRound,
  Upload,
  UserCog,
} from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { Switch } from "@/components/ui/Switch";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { useMe, useUpdateMe, useUploadMedia } from "@/api/hooks";
import { haptic } from "@/lib/tg";
import { COUNTRIES, countryFromCode } from "@/lib/countries";

/**
 * Continental "Настройки профиля" page.
 *
 * Sections (matches strings extracted from the Continental bundle):
 *   - Профиль: avatar/banner upload, display name, description.
 *   - Анонимность и безопасность: "Скрыть профиль" + "Анонимные сделки".
 *   - Уведомления: dm_deals / dm_deposits / dm_system toggles.
 *   - Безопасность: links to PIN reset and account transfer.
 */
export default function SettingsPage() {
  const navigate = useNavigate();
  const { data: me, isLoading } = useMe();
  const updateMe = useUpdateMe();
  const uploadMedia = useUploadMedia();
  const toast = useToast();
  const avatarFileRef = useRef<HTMLInputElement | null>(null);
  const bannerFileRef = useRef<HTMLInputElement | null>(null);

  const [displayName, setDisplayName] = useState<string>("");
  const [description, setDescription] = useState<string>("");
  const [bannerUrl, setBannerUrl] = useState<string>("");
  // ISO-3166-1 alpha-2 code or ``""`` for "not picked / clear it".
  // Empty string is the canonical "no country" representation in the
  // <select> tree; ``saveProfile`` maps it to ``null`` on the wire so
  // the backend column is set NULL (UserUpdate._country_ok also
  // accepts ``""`` and normalises it to None).
  const [country, setCountry] = useState<string>("");
  const [profileError, setProfileError] = useState<string | null>(null);
  const [seeded, setSeeded] = useState(false);

  if (!seeded && me) {
    setDisplayName(me.display_name || "");
    setDescription(me.description || "");
    setBannerUrl(me.banner_url || "");
    setCountry(me.country || "");
    setSeeded(true);
  }

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

  const saveProfile = async () => {
    setProfileError(null);
    try {
      await updateMe.mutateAsync({
        display_name: displayName,
        description,
        banner_url: bannerUrl ? bannerUrl : null,
        // ``""`` ⇒ ``null`` on the wire: the user explicitly chose
        // "Не выбрана" in the dropdown, which clears the column.
        country: country ? country : null,
      });
      haptic("success");
      toast.show({ kind: "success", title: "Профиль обновлён" });
    } catch (e) {
      haptic("error");
      setProfileError(await extractApiError(e));
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
        await updateMe.mutateAsync({ photo_url: uploaded.url });
      } else {
        setBannerUrl(uploaded.url);
        await updateMe.mutateAsync({ banner_url: uploaded.url });
      }
      haptic("success");
      toast.show({ kind: "success", title: kind === "avatar" ? "Аватар обновлён" : "Баннер обновлён" });
    } catch (err) {
      haptic("error");
      toast.show({ kind: "error", title: await extractApiError(err) });
    }
  };

  const togglePrivacy = async (
    field: "is_anonymous_deals" | "is_hidden_profile",
    value: boolean,
  ) => {
    try {
      await updateMe.mutateAsync({ [field]: value });
      haptic("success");
    } catch (e) {
      haptic("error");
      toast.show({ kind: "error", title: await extractApiError(e) });
    }
  };

  const toggleNotify = async (
    field: "dm_deals" | "dm_deposits" | "dm_system",
    value: boolean,
  ) => {
    try {
      await updateMe.mutateAsync({ [field]: value });
      haptic("success");
    } catch (e) {
      haptic("error");
      toast.show({ kind: "error", title: await extractApiError(e) });
    }
  };

  if (isLoading || !me) {
    return (
      <Page showBack>
        <Header title="Настройки профиля" />
        <div className="px-4 space-y-2">
          <Skeleton className="h-12 w-full rounded-button" />
          <Skeleton className="h-12 w-full rounded-button" />
          <Skeleton className="h-24 w-full rounded-card" />
          <Skeleton className="h-11 w-full rounded-button" />
        </div>
      </Page>
    );
  }

  return (
    <Page showBack>
      <Header title="Настройки профиля" />
      <div className="px-4 space-y-5">
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

        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-text-muted px-1 flex items-center gap-2">
            <UserCog className="size-4" /> Профиль
          </h2>
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
          <label className="block">
            <span className="block text-sm text-text-muted mb-1 px-1">Страна</span>
            <div className="relative">
              <select
                value={country}
                onChange={(e) => setCountry(e.target.value)}
                className="w-full appearance-none rounded-button bg-panel border border-border px-3 py-2 pr-9 text-base focus:outline-none focus:border-accent"
              >
                <option value="">Не выбрана</option>
                {COUNTRIES.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.flag} {c.name}
                  </option>
                ))}
              </select>
              {country && (
                <span
                  aria-hidden
                  className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-lg"
                >
                  {countryFromCode(country)?.flag}
                </span>
              )}
            </div>
          </label>
          {profileError && (
            <div className="text-sm text-danger whitespace-pre-line">{profileError}</div>
          )}
          <Button fullWidth onClick={saveProfile} disabled={updateMe.isPending}>
            Сохранить
          </Button>
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-text-muted px-1 flex items-center gap-2">
            <EyeOff className="size-4" /> Анонимность и безопасность
          </h2>
          <div className="bg-panel rounded-card p-3 space-y-3">
            <Switch
              checked={!!me.is_hidden_profile}
              onChange={(v) => togglePrivacy("is_hidden_profile", v)}
              label="Скрыть профиль"
              description="Профиль не будет показан в поиске"
            />
            <Switch
              checked={!!me.is_anonymous_deals}
              onChange={(v) => togglePrivacy("is_anonymous_deals", v)}
              label="Анонимные сделки"
              description="Скрывает ваш никнейм в карточках сделок"
            />
          </div>
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-text-muted px-1 flex items-center gap-2">
            <Bell className="size-4" /> Уведомления
          </h2>
          <div className="bg-panel rounded-card p-3 space-y-3">
            <Switch
              checked={me.dm_deals !== false}
              onChange={(v) => toggleNotify("dm_deals", v)}
              label="Сделки"
              description="DM-уведомления о статусе сделок"
            />
            <Switch
              checked={me.dm_deposits !== false}
              onChange={(v) => toggleNotify("dm_deposits", v)}
              label="Депозиты"
              description="Зачисления и заявки на вывод"
            />
            <Switch
              checked={me.dm_system !== false}
              onChange={(v) => toggleNotify("dm_system", v)}
              label="Системные"
              description="Новости и важные события сервиса"
            />
          </div>
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-text-muted px-1 flex items-center gap-2">
            <KeyRound className="size-4" /> Безопасность
          </h2>
          <div className="space-y-2">
            <Button
              fullWidth
              variant="secondary"
              onClick={() => navigate("/pin-reset")}
            >
              <KeyRound className="size-4" /> Сменить PIN-код
            </Button>
            <Button
              fullWidth
              variant="secondary"
              onClick={() => navigate("/change-account")}
            >
              <ArrowRightLeft className="size-4" /> Перенести аккаунт
            </Button>
          </div>
        </section>
      </div>
    </Page>
  );
}
