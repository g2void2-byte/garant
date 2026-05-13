import { X } from "lucide-react";
import type { SearchFilters } from "@/components/domain/SearchFilterSheet";

const RATING_LABELS: Record<string, string> = {
  "5.0": "Рейтинг 5.0",
  "4.5-4.9": "Рейтинг 4.5–4.9",
  "4.0-4.4": "Рейтинг 4.0–4.4",
  "3.5-3.9": "Рейтинг 3.5–3.9",
  "lt3.5": "Рейтинг ниже 3.5",
};

const DEALS_LABELS: Record<string, string> = {
  "0-10": "Сделок 0–10",
  "11-50": "Сделок 11–50",
  "51-100": "Сделок 51–100",
  "101+": "Сделок 101+",
};

const STATUS_LABELS: Record<string, string> = {
  "5": "Префикс: Администратор",
  "4": "Префикс: Модератор",
  "3": "Префикс: Арбитр",
  "2": "Префикс: VIP",
};

interface ActiveFilterChipsProps {
  value: SearchFilters;
  onRemove: (key: keyof SearchFilters) => void;
  onClearAll?: () => void;
}

interface ChipDef {
  key: keyof SearchFilters;
  label: string;
}

function buildChips(value: SearchFilters): ChipDef[] {
  const chips: ChipDef[] = [];
  if (value.rating) {
    chips.push({ key: "rating", label: RATING_LABELS[value.rating] ?? value.rating });
  }
  if (value.deals) {
    chips.push({ key: "deals", label: DEALS_LABELS[value.deals] ?? value.deals });
  }
  if (value.deposit_min) {
    chips.push({ key: "deposit_min", label: `Депозит от ${value.deposit_min}` });
  }
  if (value.status) {
    chips.push({ key: "status", label: STATUS_LABELS[value.status] ?? value.status });
  }
  if (value.reg_from) {
    chips.push({ key: "reg_from", label: `Регистрация с ${value.reg_from}` });
  }
  if (value.reg_to) {
    chips.push({ key: "reg_to", label: `Регистрация по ${value.reg_to}` });
  }
  return chips;
}

export function ActiveFilterChips({ value, onRemove, onClearAll }: ActiveFilterChipsProps) {
  const chips = buildChips(value);
  if (chips.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2" aria-label="Активные фильтры">
      {chips.map((chip) => (
        <button
          key={chip.key}
          type="button"
          onClick={() => onRemove(chip.key)}
          className="inline-flex items-center gap-1.5 px-2.5 h-7 rounded-button bg-panel-2 border border-border text-xs text-text hover:bg-secondary/40"
          aria-label={`Убрать фильтр: ${chip.label}`}
        >
          <span>{chip.label}</span>
          <X className="size-3.5" />
        </button>
      ))}
      {chips.length > 1 && onClearAll && (
        <button
          type="button"
          onClick={onClearAll}
          className="inline-flex items-center px-2.5 h-7 rounded-button text-xs text-text-muted hover:text-text"
        >
          Сбросить все
        </button>
      )}
    </div>
  );
}
