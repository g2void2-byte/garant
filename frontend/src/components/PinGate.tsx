import { lazy, Suspense, useState, type ReactNode } from "react";
import { usePinStatus } from "@/api/hooks";
import { Skeleton } from "@/components/ui/Skeleton";
import { hasValidPinToken } from "@/lib/pin";

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
