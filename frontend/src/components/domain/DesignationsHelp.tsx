import { Star, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useUI } from "@/stores/ui";
import { cn } from "@/lib/cn";

function ExampleCard({
  withPrefix,
  rating,
  deposit,
}: {
  withPrefix?: boolean;
  rating: string;
  deposit: string;
}) {
  return (
    <div className="flex items-center gap-3 bg-panel-2 border border-border rounded-2xl p-3">
      <div className="size-10 rounded-full bg-panel grid place-items-center text-text-muted font-bold">
        C
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          {withPrefix && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-accent text-accent-fg text-[11px] font-semibold leading-none">
              Арбитр
            </span>
          )}
          <span className="font-semibold truncate">Nickname</span>
          {withPrefix && <span className="size-2 rounded-full bg-success" />}
        </div>
        <div className="mt-0.5 text-xs text-text-muted">@username</div>
      </div>
      <div className="text-right shrink-0">
        <div className="inline-flex items-center gap-2 text-xs">
          <span className="text-accent font-semibold">{deposit}</span>
          <span className="inline-flex items-center gap-1 text-accent">
            <Star className="size-3" />
            {rating}
          </span>
        </div>
        <div className="mt-1 text-[11px] text-text-muted">150 сделок</div>
      </div>
    </div>
  );
}

export function DesignationsHelp() {
  const hideDesignations = useUI((s) => s.hideDesignations);
  const setHide = useUI((s) => s.setHideDesignations);

  if (hideDesignations) return null;

  return (
    <section
      className={cn("overflow-hidden animate-fadein")}
    >
      <div className="bg-panel border border-border rounded-card p-4 relative">
        <button
          className="absolute top-3 right-3 text-text-muted hover:text-text"
          aria-label="Скрыть"
          onClick={() => setHide(true)}
        >
          <X className="size-4" />
        </button>
        <div className="font-semibold">Обозначения</div>
        <p className="mt-1 text-sm text-text-muted">
          Небольшая памятка по обозначениям в карточке пользователя
        </p>

        <div className="mt-4 grid grid-cols-4 gap-2 text-[11px] text-text-muted text-center">
          <div>Префикс</div>
          <div>Статус сети</div>
          <div>Депозит</div>
          <div>Рейтинг</div>
        </div>

        <div className="mt-3 space-y-2">
          <ExampleCard withPrefix rating="4.6" deposit="$4.8k+" />
          <ExampleCard rating="4.5" deposit="$2.9k+" />
        </div>

        <Button
          variant="primary"
          size="md"
          fullWidth
          className="mt-4"
          onClick={() => setHide(true)}
        >
          Не показывать снова
        </Button>
      </div>
    </section>
  );
}
