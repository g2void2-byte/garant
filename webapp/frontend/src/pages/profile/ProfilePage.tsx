import { useNavigate } from "react-router-dom";
import { useState } from "react";
import { Plus, Wallet, Settings as SettingsIcon, Star, Link2 } from "lucide-react";
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
  useCreateDepositInvoice,
  useMe,
  useReviews,
  useServices,
  useUpdateMe,
} from "@/api/hooks";
import { haptic, openTelegramLink } from "@/lib/tg";
import { formatMoney, relativeTime } from "@/lib/format";

export default function ProfilePage() {
  const navigate = useNavigate();
  const { data: me, isLoading } = useMe();
  const [tab, setTab] = useState<"services" | "reviews">("services");
  const { data: services } = useServices({ owner: me?.username });
  const { data: reviews } = useReviews(me?.username);

  const [depositOpen, setDepositOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [forumsOpen, setForumsOpen] = useState(false);

  const updateMe = useUpdateMe();
  const createInvoice = useCreateDepositInvoice();

  const [depositAmount, setDepositAmount] = useState("50");
  const [description, setDescription] = useState("");
  const [forumName, setForumName] = useState("");
  const [forumUrl, setForumUrl] = useState("");

  if (isLoading || !me) {
    return (
      <Page>
        <div className="px-4 space-y-3 pt-3">
          <Skeleton className="h-44" />
          <Skeleton className="h-32" />
        </div>
      </Page>
    );
  }

  const handleDeposit = async () => {
    const amount = parseFloat(depositAmount);
    if (!Number.isFinite(amount) || amount <= 0) {
      haptic("error");
      return;
    }
    try {
      const invoice = await createInvoice.mutateAsync(amount);
      haptic("success");
      if (invoice.pay_url) openTelegramLink(invoice.pay_url);
      setDepositOpen(false);
    } catch {
      haptic("error");
    }
  };

  const saveDescription = async () => {
    await updateMe.mutateAsync({ description });
    haptic("success");
    setSettingsOpen(false);
  };

  const addForum = async () => {
    const forums = [...(me.forums || [])];
    forums.push({ name: forumName, url: forumUrl });
    await updateMe.mutateAsync({ forums });
    setForumName("");
    setForumUrl("");
    haptic("success");
  };

  return (
    <Page>
      <ProfileHeader user={me} />

      <div className="px-4 mt-3 space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <Button variant="primary" onClick={() => navigate("/profile/services/new")}>
            <Plus className="size-4" /> Услуга
          </Button>
          <Button variant="secondary" onClick={() => setDepositOpen(true)}>
            <Wallet className="size-4" /> Депозит
          </Button>
          <Button variant="secondary" onClick={() => setSettingsOpen(true)}>
            <SettingsIcon className="size-4" /> Настройки
          </Button>
          <Button variant="ghost" onClick={() => setForumsOpen(true)}>
            <Link2 className="size-4" /> Форумы
          </Button>
        </div>

        <ProfileStatsGrid user={me} onDepositClick={() => setDepositOpen(true)} />

        <div className="bg-panel border border-border rounded-card p-3 text-sm">
          <div className="text-text-muted">Баланс</div>
          <div className="mt-1 text-2xl font-bold text-accent">{formatMoney(me.balance)}</div>
        </div>

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
            <EmptyState title="Услуги отсутствуют" description="Нажмите «Услуга» чтобы добавить первую" />
          ) : (
            services.map((s, i) => <ServiceCard key={s.id} service={s} index={i} />)
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

      <Sheet open={depositOpen} onClose={() => setDepositOpen(false)} title="Пополнить депозит">
        <div className="space-y-3">
          <Input
            label="Сумма (USDT)"
            value={depositAmount}
            onChange={(e) => setDepositAmount(e.target.value)}
            type="number"
            min={1}
          />
          <Button fullWidth onClick={handleDeposit} disabled={createInvoice.isPending}>
            {createInvoice.isPending ? "Создаю..." : "Пополнить через CryptoBot"}
          </Button>
          <div className="text-xs text-text-muted">
            Депозит-гарант — это сумма, замороженная на профиле как гарантия добропорядочности.
          </div>
        </div>
      </Sheet>

      <Sheet open={settingsOpen} onClose={() => setSettingsOpen(false)} title="Настройки">
        <div className="space-y-3">
          <Textarea
            label="Описание профиля"
            placeholder="Расскажите о себе"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <Button fullWidth onClick={saveDescription} disabled={updateMe.isPending}>
            Сохранить
          </Button>
        </div>
      </Sheet>

      <Sheet open={forumsOpen} onClose={() => setForumsOpen(false)} title="Форумы">
        <div className="space-y-3">
          {me.forums?.map((f, i) => (
            <div key={i} className="bg-panel-2 rounded-2xl p-3 text-sm">
              <div className="font-semibold">{f.name || "—"}</div>
              <div className="text-text-muted truncate">{f.url}</div>
            </div>
          ))}
          <Input label="Название" value={forumName} onChange={(e) => setForumName(e.target.value)} />
          <Input label="Ссылка" value={forumUrl} onChange={(e) => setForumUrl(e.target.value)} />
          <Button fullWidth onClick={addForum} disabled={!forumName || !forumUrl}>
            Добавить
          </Button>
        </div>
      </Sheet>
    </Page>
  );
}
