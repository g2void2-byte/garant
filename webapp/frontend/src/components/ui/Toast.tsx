/**
 * Minimal toast system. Provides a context + hook + viewport component.
 * Animations use only transform/opacity for GPU compositing.
 */
import { AnimatePresence, motion } from "framer-motion";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Bell, CheckCircle2, XCircle, Info } from "lucide-react";
import { cn } from "@/lib/cn";

export type ToastKind = "success" | "error" | "info";

export interface ToastInput {
  kind?: ToastKind;
  title: string;
  body?: string;
  duration?: number;
  onClick?: () => void;
}

interface ToastItem extends ToastInput {
  id: number;
  kind: ToastKind;
}

interface ToastContextValue {
  show: (toast: ToastInput) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const ICONS: Record<ToastKind, React.ComponentType<{ className?: string }>> = {
  success: CheckCircle2,
  error: XCircle,
  info: Bell,
};

const KIND_CLS: Record<ToastKind, string> = {
  success: "border-success/40 bg-success/10",
  error: "border-danger/40 bg-danger/10",
  info: "border-border bg-panel",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const counter = useRef(0);

  const show = useCallback((toast: ToastInput) => {
    counter.current += 1;
    const id = counter.current;
    const item: ToastItem = {
      id,
      kind: toast.kind ?? "info",
      title: toast.title,
      body: toast.body,
      duration: toast.duration ?? 4000,
      onClick: toast.onClick,
    };
    setItems((prev) => [...prev, item]);
    if (item.duration && item.duration > 0) {
      window.setTimeout(() => {
        setItems((prev) => prev.filter((t) => t.id !== id));
      }, item.duration);
    }
  }, []);

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const value = useMemo(() => ({ show }), [show]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="fixed inset-x-0 top-3 z-[60] flex flex-col items-center gap-2 px-3 pointer-events-none"
        aria-live="polite"
      >
        <AnimatePresence initial={false}>
          {items.map((item) => {
            const Icon = ICONS[item.kind] ?? Info;
            return (
              <motion.button
                key={item.id}
                layout
                initial={{ opacity: 0, y: -16, scale: 0.96 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -8, scale: 0.96 }}
                transition={{ type: "spring", stiffness: 500, damping: 32 }}
                onClick={() => {
                  item.onClick?.();
                  dismiss(item.id);
                }}
                className={cn(
                  "pointer-events-auto w-full max-w-[460px] text-left",
                  "flex items-start gap-3 p-3 rounded-card border shadow-pop backdrop-blur",
                  KIND_CLS[item.kind],
                )}
              >
                <div className="size-9 grid place-items-center rounded-full bg-panel-2 shrink-0">
                  <Icon className="size-5" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-semibold truncate">{item.title}</div>
                  {item.body && <div className="mt-0.5 text-sm text-text-muted line-clamp-2">{item.body}</div>}
                </div>
              </motion.button>
            );
          })}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    // Allow components to be rendered outside the provider (e.g. in tests)
    // without throwing — fall back to console.
    return {
      show: (t) => {
        if (typeof console !== "undefined") {
          console.info("[toast]", t.title, t.body ?? "");
        }
      },
    };
  }
  return ctx;
}
