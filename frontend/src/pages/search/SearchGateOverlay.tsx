import { useNavigate } from "react-router-dom";
import { ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface SearchGateOverlayProps {
  message: string;
}

export function SearchGateOverlay({ message }: SearchGateOverlayProps) {
  const navigate = useNavigate();
  return (
    <div className="absolute inset-0 bg-black/10 backdrop-blur-[1px] z-10 overflow-y-auto p-4 flex items-center justify-center">
      <div className="my-auto bg-panel/95 border border-border rounded-2xl p-5 shadow-2xl max-w-sm text-center animate-fade-in-scale">
        <div className="size-12 mx-auto rounded-full bg-accent/15 text-accent grid place-items-center mb-3">
          <ShieldAlert className="size-6" />
        </div>
        <h3 className="font-semibold text-lg text-text">Поиск ограничен</h3>
        <p className="text-[13px] text-text-muted mt-2 leading-relaxed">
          {message}
        </p>
        <Button size="sm" className="mt-4 w-full" onClick={() => navigate("/deals")}>
          Перейти к сделкам
        </Button>
      </div>
    </div>
  );
}
