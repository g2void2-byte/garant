import { useEffect, useState } from "react";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { cn } from "@/lib/cn";

/**
 * Continental's "Применить фильтры" bottom-sheet. Four sections:
 *
 *  1. Рейтинг          — single-select: 5.0 / 4.5-4.9 / 4.0-4.4 / 3.5-3.9 / Ниже 3.5
 *  2. Количество сделок — single-select: 0-10 / 11-50 / 51-100 / 101+
 *  3. Префикс          — single-select: Администратор / Модератор / Арбитр / VIP
 *  4. Дата регистрации — От / До date inputs
 *
 * On Apply the parent receives the new filter object and is responsible
 * for refetching ``GET /api/users`` with the matching query params.
 *
 * The “Депозит” section was retired together with
 * ``User.deposit_total`` — there is no longer a lifetime deposit
 * column to filter by; the user-visible “Депозит” on the profile
 * page is the lock-in trust deposit, which is not searchable.
 */
export interface SearchFilters {
  rating?: string;
  deals?: string;
  status?: string;
  reg_from?: string;
  reg_to?: string;
}

interface SearchFilterSheetProps {
  open: boolean;
  onClose: () => void;
  value: SearchFilters;
  onApply: (next: SearchFilters) => void;
}

const RATING_OPTIONS = [
  { value: "5.0", label: "5.0" },
  { value: "4.5-4.9", label: "4.5 – 4.9" },
  { value: "4.0-4.4", label: "4.0 – 4.4" },
  { value: "3.5-3.9", label: "3.5 – 3.9" },
  { value: "lt3.5", label: "Ниже 3.5" },
];

const DEALS_OPTIONS = [
  { value: "0-10", label: "0 – 10" },
  { value: "11-50", label: "11 – 50" },
  { value: "51-100", label: "51 – 100" },
  { value: "101+", label: "101 +" },
];

const STATUS_OPTIONS = [
  { value: "5", label: "Администратор" },
  { value: "4", label: "Модератор" },
  { value: "3", label: "Арбитр" },
  { value: "2", label: "VIP" },
];

function RadioRow({
  options,
  value,
  onChange,
}: {
  options: { value: string; label: string }[];
  value: string | undefined;
  onChange: (v: string | undefined) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((opt) => {
        const checked = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(checked ? undefined : opt.value)}
            className={cn(
              "px-3 h-9 rounded-button text-sm font-medium transition-colors",
              checked
                ? "bg-accent text-accent-fg"
                : "bg-panel-2 text-text border border-border hover:bg-secondary/40",
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

export function SearchFilterSheet({
  open,
  onClose,
  value,
  onApply,
}: SearchFilterSheetProps) {
  const [local, setLocal] = useState<SearchFilters>(value);

  // Sync local state when the sheet is reopened with new external state.
  useEffect(() => {
    if (open) setLocal(value);
  }, [open, value]);

  const reset = () => setLocal({});
  const apply = () => {
    onApply(local);
    onClose();
  };

  return (
    <Sheet open={open} onClose={onClose} title="Фильтры">
      {/* V13 — extra bottom padding on the scroll body lets the
          sticky button bar sit clear of the safe-area inset and
          guarantees the last filter section is never hidden behind
          the buttons. */}
      <div className="space-y-5 pb-32 pt-1">
        <section>
          <h3 className="text-base font-semibold mb-2">Рейтинг</h3>
          <RadioRow
            options={RATING_OPTIONS}
            value={local.rating}
            onChange={(v) => setLocal({ ...local, rating: v })}
          />
        </section>

        <section>
          <h3 className="text-base font-semibold mb-2">Количество сделок</h3>
          <RadioRow
            options={DEALS_OPTIONS}
            value={local.deals}
            onChange={(v) => setLocal({ ...local, deals: v })}
          />
        </section>

        <section>
          <h3 className="text-base font-semibold mb-2">Префикс</h3>
          <RadioRow
            options={STATUS_OPTIONS}
            value={local.status}
            onChange={(v) => setLocal({ ...local, status: v })}
          />
        </section>

        <section>
          <h3 className="text-base font-semibold mb-2">Дата регистрации</h3>
          <div className="grid grid-cols-2 gap-2">
            <Input
              type="date"
              placeholder="От"
              value={local.reg_from ?? ""}
              onChange={(e) =>
                setLocal({
                  ...local,
                  reg_from: e.target.value ? e.target.value : undefined,
                })
              }
            />
            <Input
              type="date"
              placeholder="До"
              value={local.reg_to ?? ""}
              onChange={(e) =>
                setLocal({
                  ...local,
                  reg_to: e.target.value ? e.target.value : undefined,
                })
              }
            />
          </div>
        </section>

      </div>
      {/* V13 — sticky bottom bar so the "Применить" / "Сбросить"
          buttons stay anchored on long forms. ``-mx-4 px-4`` cancels
          the parent's horizontal padding so the bar reaches the
          sheet edges; ``backdrop-blur-sm`` softens the content
          peeking through behind it on iOS. */}
      <div
        className={cn(
          "sticky bottom-0 -mx-4 px-4 pt-3 pb-4 bg-panel/95 backdrop-blur-sm",
          "border-t border-border",
          "grid grid-cols-2 gap-2",
        )}
      >
        <Button variant="secondary" onClick={reset}>
          Сбросить
        </Button>
        <Button variant="primary" onClick={apply}>
          Применить фильтры
        </Button>
      </div>
    </Sheet>
  );
}
