import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Search, Star, X } from "lucide-react";
import { useUsers } from "@/api/hooks";
import type { UserCardDto } from "@/api/types";
import { Avatar } from "@/components/ui/Avatar";
import { BadgePrefix } from "@/components/ui/BadgePrefix";
import { OnlineDot } from "@/components/ui/OnlineDot";
import { Button } from "@/components/ui/Button";
import { dealsLabel } from "@/lib/format";
import { staggerDelay } from "@/lib/animate";
import { cn } from "@/lib/cn";

interface UserPickerProps {
  /** Selected username (without ``@``). ``""`` means "nothing picked". */
  value: string;
  /** Fired with the username (without ``@``) on every change. */
  onChange: (username: string) => void;
  /**
   * Optional callback fired with the full ``UserCardDto`` whenever a
   * row is picked from the dropdown, and with ``null`` when the
   * selection is cleared. Callers that need the picked user's ``id``
   * (e.g. the admin "Новый отзыв" sheet) use this to avoid a
   * secondary lookup-by-username round trip. Backwards-compatible —
   * ``CreateDealPage`` does not pass this prop and continues to drive
   * itself off ``value``/``onChange``.
   */
  onPick?: (user: UserCardDto | null) => void;
  /**
   * Optional "Start deal" callback. When provided, the selected-card
   * footer renders a primary "Начать сделку" button; when omitted the
   * caller can drive submission from elsewhere on the form (e.g. a
   * single button at the bottom of the page).
   */
  onStartDeal?: (user: UserCardDto) => void;
  /** Label for the search input. */
  label?: string;
  placeholder?: string;
  /** Debounce in ms before triggering the lookup. */
  debounceMs?: number;
}

/**
 * Animated user-search picker used on ``/deals/new``.
 *
 * The user types a username or numeric ID and the dropdown surfaces
 * the matching ``/api/users?q=…`` rows in real time (350 ms debounce
 * keeps the request rate sane). Tapping a row collapses the dropdown
 * and renders a highlighted "selected" card with "Профиль" + "Начать
 * сделку" affordances. Hitting the inline ✕ on the selected card
 * re-opens the picker so the user can swap their counterparty without
 * leaving the page.
 */
export function UserPicker({
  value,
  onChange,
  onPick,
  onStartDeal,
  label = "Контрагент",
  placeholder = "@username или ID",
  debounceMs = 350,
}: UserPickerProps) {
  const [input, setInput] = useState(value);
  const [focused, setFocused] = useState(false);
  const [debounced, setDebounced] = useState(value);
  const [selected, setSelected] = useState<UserCardDto | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef(input);
  inputRef.current = input;

  // Keep the displayed input in sync with ``value`` when the parent
  // pushes a username down (e.g. ``?to=alice`` query-string seed).
  // ``inputRef`` shadows the latest ``input`` state without making it
  // a hook dep — re-running this effect after every keystroke would
  // otherwise clobber the user's edit mid-typing whenever ``value``
  // lagged behind by one render.
  useEffect(() => {
    if (value && value !== inputRef.current) {
      setInput(value);
      setDebounced(value);
    }
  }, [value]);

  // Debounce the live-search request so we don't fire on every
  // keystroke. The "5 ms" the user mentioned is hyperbolic — the
  // observable behaviour they want is "suggestions appear quickly
  // after I stop typing", which 350 ms achieves without hammering the
  // backend.
  useEffect(() => {
    const id = setTimeout(() => setDebounced(input), debounceMs);
    return () => clearTimeout(id);
  }, [input, debounceMs]);

  // Normalise leading ``@`` so the server receives the bare username.
  const normalized = useMemo(() => debounced.replace(/^@+/, "").trim(), [debounced]);
  const { data: users, isLoading } = useUsers(
    normalized ? { q: normalized, picker: true } : { picker: true },
  );

  // Close on outside click so the dropdown doesn't linger when the
  // user taps somewhere else on the form.
  useEffect(() => {
    if (!focused) return;
    function onDown(e: PointerEvent) {
      const root = wrapRef.current;
      if (!root) return;
      if (e.target instanceof Node && root.contains(e.target)) return;
      setFocused(false);
    }
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [focused]);

  function pickUser(u: UserCardDto) {
    setSelected(u);
    setInput(u.username);
    onChange(u.username);
    onPick?.(u);
    setFocused(false);
  }

  function clearSelection() {
    setSelected(null);
    setInput("");
    setDebounced("");
    onChange("");
    onPick?.(null);
    setFocused(true);
  }

  const showDropdown =
    focused && !selected && normalized.length > 0;
  const filtered = users ?? [];

  return (
    <div ref={wrapRef} className="relative">
      {label && (
        <div className="mb-1 text-[14px] font-medium text-text">{label}</div>
      )}

      {selected ? (
        <SelectedUserCard
          user={selected}
          onChange={clearSelection}
          onStartDeal={onStartDeal}
        />
      ) : (
        <div
          className={cn(
            "flex items-center gap-2 h-11 px-3 rounded-button bg-panel border border-border",
            "transition-colors",
            focused && "border-accent/60 ring-1 ring-accent/30",
          )}
        >
          <Search className="size-4 text-text-muted shrink-0" />
          <input
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              if (selected) {
                setSelected(null);
                onPick?.(null);
              }
              onChange(e.target.value.replace(/^@+/, "").trim());
            }}
            onFocus={() => setFocused(true)}
            placeholder={placeholder}
            inputMode="text"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
            className="flex-1 min-w-0 bg-transparent text-text outline-none placeholder:text-text-muted"
            aria-label={label}
          />
          {input && (
            <button
              type="button"
              aria-label="Очистить"
              className="size-6 grid place-items-center rounded-full text-text-muted hover:bg-secondary active:scale-95 transition"
              onClick={() => {
                setInput("");
                setDebounced("");
                onChange("");
              }}
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>
      )}

      {showDropdown && (
        <div
          role="listbox"
          aria-label="Возможные пользователи"
          className={cn(
            "absolute left-0 right-0 z-30 mt-1.5 rounded-card bg-panel border border-border shadow-pop",
            "overflow-hidden animate-fade-in-down",
          )}
        >
          <div className="max-h-72 overflow-y-auto">
            {isLoading ? (
              <div className="p-4 text-center text-text-muted text-sm">
                Ищем пользователей…
              </div>
            ) : filtered.length === 0 ? (
              <div className="p-4 text-center text-text-muted text-sm">
                Никого не найдено по запросу «{normalized}»
              </div>
            ) : (
              <ul className="py-1.5">
                {filtered.slice(0, 8).map((u, i) => (
                  <li
                    key={u.id}
                    style={staggerDelay(i, 25, 200)}
                    className="animate-fade-in-down"
                  >
                    <button
                      type="button"
                      role="option"
                      aria-selected={value === u.username}
                      onClick={() => pickUser(u)}
                      className={cn(
                        "w-full flex items-center gap-3 px-3 py-2 text-left",
                        "hover:bg-secondary/60 active:bg-secondary",
                        "transition-colors",
                      )}
                    >
                      <div className="relative shrink-0">
                        <Avatar
                          name={u.username}
                          src={u.photo_url}
                          size={40}
                        />
                        <span className="absolute -bottom-0.5 -right-0.5 ring-2 ring-panel rounded-full">
                          <OnlineDot online={u.online} />
                        </span>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <BadgePrefix prefix={u.prefix} />
                          <span className="font-medium text-[15px] truncate">
                            {u.display_name?.trim() || u.username}
                          </span>
                        </div>
                        <div className="text-[12px] text-text-muted truncate">
                          @{u.username}
                        </div>
                      </div>
                      <div className="flex flex-col items-end shrink-0 gap-0.5">
                        <span className="inline-flex items-center gap-1 text-accent text-[12px] font-semibold">
                          <Star className="size-3" strokeWidth={2.5} />
                          {u.reviews_count
                            ? u.rating.toFixed(1)
                            : "0.0"}
                        </span>
                        <span className="text-[11px] text-text-muted tabular-nums">
                          {dealsLabel(u.deals_count)}
                        </span>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

interface SelectedUserCardProps {
  user: UserCardDto;
  onChange: () => void;
  onStartDeal?: (user: UserCardDto) => void;
}

function SelectedUserCard({
  user,
  onChange,
  onStartDeal,
}: SelectedUserCardProps) {
  const ratingLabel = user.reviews_count
    ? user.rating.toFixed(1)
    : "0.0";

  return (
    <div className="rounded-card bg-panel border border-accent/50 shadow-glow p-3 animate-fade-in-scale">
      <div className="flex items-center gap-3">
        <div className="relative shrink-0">
          <Avatar name={user.username} src={user.photo_url} size={48} />
          <span className="absolute -bottom-0.5 -right-0.5 ring-2 ring-panel rounded-full">
            <OnlineDot online={user.online} />
          </span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <BadgePrefix prefix={user.prefix} />
            <span className="font-semibold text-[15px] truncate">
              {user.display_name?.trim() || user.username}
            </span>
          </div>
          <div className="text-[12px] text-text-muted truncate">
            @{user.username} · {dealsLabel(user.deals_count)} ·
            <span className="ml-1 inline-flex items-center gap-1 text-accent font-medium">
              <Star className="size-3" strokeWidth={2.5} />
              {ratingLabel}
            </span>
          </div>
        </div>
        <button
          type="button"
          aria-label="Сменить пользователя"
          onClick={onChange}
          className="size-8 grid place-items-center rounded-full text-text-muted hover:bg-secondary active:scale-95 transition"
        >
          <X className="size-4" />
        </button>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Link
          to={`/users/${user.username}`}
          className="h-10 rounded-button bg-secondary text-text font-medium flex items-center justify-center text-[14px] hover:opacity-90 active:opacity-80 transition"
        >
          Профиль
        </Link>
        {onStartDeal ? (
          <Button
            size="md"
            onClick={() => onStartDeal(user)}
            className="!h-10 !text-[14px]"
          >
            Начать сделку
          </Button>
        ) : (
          <div className="h-10 rounded-button bg-accent/20 text-accent font-medium flex items-center justify-center text-[14px]">
            Готов к сделке
          </div>
        )}
      </div>
    </div>
  );
}
