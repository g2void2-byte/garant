import { useNavigate } from "react-router-dom";
import { useRef, useState } from "react";
import { ImagePlus, Trash2 } from "lucide-react";
import { Header } from "@/components/layout/Header";
import { Page } from "@/components/layout/Page";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { Select } from "@/components/ui/Select";
import { useToast } from "@/components/ui/Toast";
import { useCategories, useCreateService, useUploadMedia } from "@/api/hooks";
import { haptic } from "@/lib/tg";

// V12-UI — inline copy of the helper used elsewhere (SettingsPage,
// AddForumPage). Kept local to avoid a one-off shared module just for
// three callers; the shape (HTTPError → detail string) is identical.
async function extractApiError(e: unknown): Promise<string> {
  const anyErr = e as { response?: Response; message?: string };
  if (anyErr?.response) {
    try {
      const j = (await anyErr.response.clone().json()) as { detail?: string };
      if (j?.detail) return j.detail;
    } catch {
      // fall through to text/message below
    }
    try {
      const txt = await anyErr.response.clone().text();
      if (txt) return txt;
    } catch {
      // ignore
    }
  }
  return anyErr?.message || "Не удалось выполнить операцию";
}

const MAX_PHOTOS = 6;

export default function AddServicePage() {
  const navigate = useNavigate();
  const toast = useToast();
  const { data: categories } = useCategories();
  const create = useCreateService();
  const uploadMedia = useUploadMedia();

  const [slug, setSlug] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [price, setPrice] = useState("");
  const [photoUrls, setPhotoUrls] = useState<string[]>([]);

  const fileRef = useRef<HTMLInputElement>(null);

  const onPickPhotos = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    if (!files.length) return;
    const free = MAX_PHOTOS - photoUrls.length;
    if (free <= 0) {
      toast.show({ kind: "error", title: `Можно прикрепить не более ${MAX_PHOTOS} фотографий` });
      return;
    }
    const slice = files.slice(0, free);
    if (files.length > slice.length) {
      toast.show({ kind: "info", title: `Загрузили только ${slice.length} из ${files.length}` });
    }
    for (const file of slice) {
      try {
        const m = await uploadMedia.mutateAsync({ kind: "service", file });
        setPhotoUrls((prev) => (prev.length >= MAX_PHOTOS ? prev : [...prev, m.url]));
        haptic("light");
      } catch (err) {
        haptic("error");
        toast.show({ kind: "error", title: await extractApiError(err) });
      }
    }
  };

  const removePhoto = (idx: number) => {
    setPhotoUrls((prev) => prev.filter((_, i) => i !== idx));
    haptic("light");
  };

  const submit = async () => {
    if (!slug || !title) {
      toast.show({ kind: "error", title: "Заполните категорию и название" });
      haptic("error");
      return;
    }
    try {
      await create.mutateAsync({
        category_slug: slug,
        title,
        description,
        price: parseFloat(price) || 0,
        photo_urls: photoUrls,
      });
      haptic("success");
      navigate(-1);
    } catch (err) {
      haptic("error");
      toast.show({ kind: "error", title: await extractApiError(err) });
    }
  };

  return (
    <Page showBack>
      <Header title="Новая услуга" subtitle="Заполните данные о вашей услуге" />
      <div className="px-4 space-y-3">
        <Select
          value={slug}
          options={(categories ?? []).map((c) => ({ value: c.slug, label: c.name }))}
          onChange={setSlug}
          placeholder="Выберите категорию"
          withIcon={false}
        />
        <Input label="Название" placeholder="Краткое название услуги" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Textarea label="Описание" placeholder="Что входит, условия, сроки..." value={description} onChange={(e) => setDescription(e.target.value)} />
        <Input
          label="Цена (USDT)"
          type="number"
          value={price}
          min={0}
          step={0.01}
          onChange={(e) => setPrice(e.target.value)}
        />

        <div className="space-y-2">
          <div className="flex items-center justify-between px-1">
            <span className="text-sm text-text-muted">
              Фотографии услуги ({photoUrls.length}/{MAX_PHOTOS})
            </span>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            className="hidden"
            multiple
            onChange={onPickPhotos}
          />
          <div className="grid grid-cols-3 gap-2">
            {photoUrls.map((url, idx) => (
              <div
                key={`${url}-${idx}`}
                className="relative aspect-square rounded-button overflow-hidden border border-border bg-panel-2"
              >
                <img src={url} alt="" className="absolute inset-0 size-full object-cover" />
                <button
                  type="button"
                  onClick={() => removePhoto(idx)}
                  className="absolute top-1 right-1 size-7 grid place-items-center rounded-full bg-black/60 text-white active:scale-90"
                  aria-label="Удалить фото"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            ))}
            {photoUrls.length < MAX_PHOTOS && (
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                disabled={uploadMedia.isPending}
                className="aspect-square rounded-button border-2 border-dashed border-border text-text-muted grid place-items-center gap-1 active:scale-95 transition-transform disabled:opacity-50"
              >
                <ImagePlus className="size-5" />
                <span className="text-[11px]">Добавить</span>
              </button>
            )}
          </div>
        </div>

        <Button fullWidth onClick={submit} disabled={create.isPending || uploadMedia.isPending}>
          {create.isPending ? "Сохраняю..." : "Создать услугу"}
        </Button>
      </div>
    </Page>
  );
}
