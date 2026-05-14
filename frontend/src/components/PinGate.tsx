import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { usePinStatus } from "@/api/hooks";
import { Skeleton } from "@/components/ui/Skeleton";
import { PIN_TOKEN_CHANGED_EVENT, hasValidPinToken } from "@/lib/pin";

const PinPage = lazy(() => import("@/pages/pin/PinPage"));

function FullScreenLoader() {
  return (
    <div className="min-h-full flex items-center justify-center p-6">
      <div className="w-full max-w-sm space-y-4">
        <Skeleton className="h-8 w-1/2 mx-auto" />
        <Skeleton className="h-3 w-3/4 mx-auto" />
        <div className="grid grid-cols-3 gap-3 mt-8">
          {Array.from({ length: 12 }).map((_, i) => (
            <Skeleton key={i} className="h-[60px] w-full rounded-lg" />
          ))}
        </div>
      </div>
    </div>
  );
}

export function PinGate({ children }: { children: ReactNode }) {
  const status = usePinStatus();
  const [unlocked, setUnlocked] = useState(hasValidPinToken());

  // Re-sync ``unlocked`` whenever the token is mutated from outside
  // this component. The ky 401 interceptor in ``api/client.ts`` calls
  // ``clearPinToken()`` when the server returns "PIN-сессия отозвана";
  // without this listener the UI would stay in the authenticated tree
  // until the next reload.
  useEffect(() => {
    const onChange = () => setUnlocked(hasValidPinToken());
    window.addEventListener(PIN_TOKEN_CHANGED_EVENT, onChange);
    window.addEventListener("storage", onChange);
    return () => {
      window.removeEventListener(PIN_TOKEN_CHANGED_EVENT, onChange);
      window.removeEventListener("storage", onChange);
    };
  }, []);

  if (status.isLoading || !status.data) return <FullScreenLoader />;
  if (status.isError) {
    return (
      <div className="min-h-full flex items-center justify-center p-6 text-text-muted text-sm text-center">
        Не удалось связаться с сервером. Попробуйте обновить страницу.
      </div>
    );
  }

  if (unlocked) return <>{children}</>;

  return (
    <Suspense fallback={<FullScreenLoader />}>
      <PinPage status={status.data} onUnlocked={() => setUnlocked(true)} />
    </Suspense>
  );
}
