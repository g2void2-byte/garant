import { useState } from "react";
import { ChevronDown, HelpCircle } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { cn } from "@/lib/cn";
import { haptic } from "@/lib/tg";

interface FaqSection {
  id: string;
  title: string;
  /** Plain-text paragraphs rendered one per line in the expanded body. */
  body: string[];
}

/**
 * FAQ catalogue rendered as a collapsible accordion. Mirrors the
 * structure of the reference TMA the product spec references (a
 * welcome card on top, then a stack of expandable rule sections).
 * Content is intentionally hard-coded for the V14 cut — the data
 * shape is kept narrow so the FAQ can be moved to an admin-editable
 * DB table later without touching the rendering layer.
 */
const FAQ_SECTIONS: FaqSection[] = [
  {
    id: "rules",
    title: "Полные правила",
    body: [
      "Гарант-бот обслуживает сделки между продавцом и покупателем по модели escrow: средства покупателя замораживаются на балансе и переводятся продавцу только после подтверждения получения товара/услуги.",
      "Запрещены сделки с предметами вне правил площадки: запрещённые товары, мошеннические схемы, нелегальные услуги, передача чужих аккаунтов без согласия владельца, любые операции, нарушающие законы стран сторон.",
      "Спорные ситуации рассматривает арбитраж. Решение арбитра обязательно для обеих сторон сделки.",
    ],
  },
  {
    id: "tos",
    title: "Пользовательское соглашение",
    body: [
      "Используя гарант-бот, вы соглашаетесь с правилами площадки, политикой конфиденциальности и сроками обработки сделок.",
      "Платформа выступает посредником и не является стороной по сделке между пользователями. Все материальные обязательства лежат на сторонах.",
      "Аккаунт привязан к вашему Telegram ID. Передача аккаунта возможна только через встроенную функцию переноса; деление одного аккаунта между несколькими людьми запрещено.",
    ],
  },
  {
    id: "guarantor",
    title: "Правила пользования гарантом",
    body: [
      "Перед открытием сделки убедитесь, что описание услуги/товара совпадает с тем, что обсуждали в переговорах.",
      "Покупатель пополняет баланс и подтверждает депонирование суммы по сделке. Продавец видит подтверждение и выполняет обязательства.",
      "После получения товара/услуги покупатель подтверждает завершение сделки — средства списываются с эскроу и зачисляются продавцу за вычетом комиссии 5%.",
      "Если что-то пошло не так — открывайте арбитраж в сделке. Арбитр запросит доказательства и вынесет решение.",
    ],
  },
  {
    id: "auto",
    title: "Как пользоваться автогарантом",
    body: [
      "Автогарант — это режим без ручного согласования каждой суммы: продавец публикует услугу с фиксированной ценой, покупатель оформляет сделку прямо из карточки услуги.",
      "Откройте раздел «Поиск», найдите интересующую услугу, нажмите «Создать сделку», введите детали и оплатите депозит.",
      "Дальше всё как в обычном гаранте: продавец выполняет обязательство, вы подтверждаете и средства уходят продавцу.",
    ],
  },
  {
    id: "fees",
    title: "Комиссии и лимиты",
    body: [
      "Комиссия гаранта: 5% от суммы сделки. Вычитается из выплаты продавцу при успешном завершении.",
      "Комиссии платёжных систем (CryptoBot, Crystalpay) зависят от выбранной валюты/сети и удерживаются провайдером на этапе пополнения/вывода.",
      "Минимальная и максимальная сумма зависит от валюты и отображается на странице пополнения и в карточке услуги.",
    ],
  },
  {
    id: "withdraw",
    title: "Пополнение и вывод средств",
    body: [
      "Пополнить баланс можно через CryptoBot или Crystalpay в разделе «Кошелёк» → «Пополнить». Поддерживаются криптовалюты и фиатные счета провайдеров.",
      "Окно с реальным статусом инвойса обновляется автоматически — как только платёж зайдёт, баланс пополнится без перезагрузки страницы.",
      "Вывод доступен на криптокошелёк (адрес указывается на странице вывода). Вывод на банковскую карту обрабатывается администрацией вручную.",
    ],
  },
  {
    id: "support",
    title: "Что делать, если что-то пошло не так",
    body: [
      "Сначала проверьте статус сделки в разделе «Сделки» — там фиксируется каждое действие сторон.",
      "Если контрагент не отвечает или нарушает условия — откройте арбитраж в карточке сделки. Арбитр получит уведомление и подключится к разбору.",
      "При технических проблемах с приложением (зависает, не приходит платёж, не отображается баланс) — попробуйте перезапустить Mini App и проверить интернет. Если проблема повторяется, опишите её детально через раздел «Сделки» → «Арбитраж».",
    ],
  },
];

function FaqRow({
  section,
  open,
  onToggle,
}: {
  section: FaqSection;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      className={cn(
        "rounded-card border border-border bg-panel overflow-hidden transition-colors",
        open && "border-accent/40",
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="w-full flex items-center gap-3 px-4 py-3 text-left active:opacity-80 transition"
      >
        <ChevronDown
          className={cn(
            "size-4 shrink-0 text-text-muted transition-transform",
            open ? "rotate-0 text-accent" : "-rotate-90",
          )}
          strokeWidth={2}
        />
        <span className="flex-1 text-[14px] font-medium text-text">
          {section.title}
        </span>
      </button>
      <div
        className={cn(
          "grid transition-[grid-template-rows] duration-200 ease-out",
          open ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
        )}
      >
        <div className="overflow-hidden">
          <div className="px-4 pb-4 pt-1 space-y-2 text-[13px] leading-relaxed text-text-muted">
            {section.body.map((p, i) => (
              <p key={i}>{p}</p>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function HelpPage() {
  const [openId, setOpenId] = useState<string | null>(null);

  function toggle(id: string) {
    haptic("light");
    setOpenId((prev) => (prev === id ? null : id));
  }

  return (
    <Page>
      <Header title="Помощь" />
      <div className="px-4 space-y-3 pb-4">
        <div className="rounded-card border border-border bg-panel p-4">
          <div className="flex items-start gap-3">
            <div className="size-10 grid place-items-center rounded-2xl bg-accent/15 text-accent shrink-0">
              <HelpCircle className="size-5" />
            </div>
            <div className="min-w-0">
              <div className="text-[16px] font-semibold tracking-tight text-text">
                FAQ EW Гарант
              </div>
              <p className="text-[13px] text-text-muted leading-relaxed mt-1">
                Добро пожаловать! Здесь собраны ответы на основные вопросы по
                работе с гаранту, оплатам, выплатам и арбитражу. Раскройте
                нужный раздел, чтобы прочитать подробности.
              </p>
            </div>
          </div>
        </div>

        <div className="space-y-2">
          {FAQ_SECTIONS.map((section) => (
            <FaqRow
              key={section.id}
              section={section}
              open={openId === section.id}
              onToggle={() => toggle(section.id)}
            />
          ))}
        </div>
      </div>
    </Page>
  );
}
