import { useNavigate } from "react-router-dom";
import { useState } from "react";
import { Header } from "@/components/layout/Header";
import { Page } from "@/components/layout/Page";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { Select } from "@/components/ui/Select";
import { useCategories, useCreateService } from "@/api/hooks";
import { haptic } from "@/lib/tg";

export default function AddServicePage() {
  const navigate = useNavigate();
  const { data: categories } = useCategories();
  const create = useCreateService();

  const [slug, setSlug] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [price, setPrice] = useState("");

  const submit = async () => {
    if (!slug || !title) {
      haptic("error");
      return;
    }
    try {
      await create.mutateAsync({ category_slug: slug, title, description, price: parseFloat(price) || 0 });
      haptic("success");
      navigate(-1);
    } catch {
      haptic("error");
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
        <Button fullWidth onClick={submit} disabled={create.isPending}>
          {create.isPending ? "Сохраняю..." : "Создать услугу"}
        </Button>
      </div>
    </Page>
  );
}
