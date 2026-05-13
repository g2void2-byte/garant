import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useUI } from "@/stores/ui";

export function DesignationsHelp() {
  const hideDesignations = useUI((s) => s.hideDesignations);
  const setHide = useUI((s) => s.setHideDesignations);

  return (
    <AnimatePresence initial={false}>
      {!hideDesignations && (
        <motion.section
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          transition={{ duration: 0.25 }}
          className="overflow-hidden"
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
            <ul className="mt-3 space-y-2 text-sm text-text-muted">
              <li>
                <span className="inline-flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded-full bg-accent text-accent-fg text-[11px] font-bold">Префикс</span>
                  <span>— роль (Арбитр, Админ)</span>
                </span>
              </li>
              <li>
                <span className="inline-flex items-center gap-2">
                  <span className="size-2 rounded-full bg-success" />
                  <span>— статус в сети (онлайн)</span>
                </span>
              </li>
              <li>
                <span className="inline-flex items-center gap-2 text-accent font-semibold">$1.2k+</span>
                <span className="ml-2">— активный депозит-гарант</span>
              </li>
              <li>
                <span className="inline-flex items-center gap-2 text-accent">★ 4.8</span>
                <span className="ml-2">— средний рейтинг по отзывам</span>
              </li>
            </ul>
            <Button variant="ghost" size="sm" className="mt-3" onClick={() => setHide(true)}>
              Не показывать снова
            </Button>
          </div>
        </motion.section>
      )}
    </AnimatePresence>
  );
}
