import { AnimatePresence, motion } from "framer-motion";
import { useEffect, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { showBackButton } from "@/lib/tg";

interface PageProps {
  children: ReactNode;
  showBack?: boolean;
  onBack?: () => void;
}

export function Page({ children, showBack, onBack }: PageProps) {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (!showBack) return;
    return showBackButton(() => {
      if (onBack) onBack();
      else navigate(-1);
    });
  }, [showBack, onBack, navigate]);

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={location.pathname}
        initial={{ opacity: 0, x: 16 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: -16 }}
        transition={{ duration: 0.18, ease: "easeOut" }}
        className="min-h-full pb-[96px]"
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
