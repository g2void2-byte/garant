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
    <div
      key={location.pathname}
      className="min-h-full pb-[96px] animate-fadein"
    >
      {children}
    </div>
  );
}
