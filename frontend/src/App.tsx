import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { PinGate } from "@/components/PinGate";
import { BottomNav } from "@/components/layout/BottomNav";
import { Skeleton } from "@/components/ui/Skeleton";
import { ToastProvider } from "@/components/ui/Toast";
import { useLiveNotifications } from "@/lib/useLiveNotifications";
import { initTelegram } from "@/lib/tg";

const SearchPage = lazy(() => import("@/pages/search/SearchPage"));
const CategoriesPage = lazy(() => import("@/pages/search/CategoriesPage"));
const UserProfilePage = lazy(() => import("@/pages/search/UserProfilePage"));
const DealsPage = lazy(() => import("@/pages/deals/DealsPage"));
const DealDetailPage = lazy(() => import("@/pages/deals/DealDetailPage"));
const CreateDealPage = lazy(() => import("@/pages/deals/CreateDealPage"));
const HelpPage = lazy(() => import("@/pages/help/HelpPage"));
const NotificationsPage = lazy(() => import("@/pages/notifications/NotificationsPage"));
const ProfilePage = lazy(() => import("@/pages/profile/ProfilePage"));
const AddServicePage = lazy(() => import("@/pages/profile/AddServicePage"));
const DepositPage = lazy(() => import("@/pages/profile/DepositPage"));
const WalletPage = lazy(() => import("@/pages/wallet/WalletPage"));
const WalletCurrencyPage = lazy(() => import("@/pages/wallet/WalletCurrencyPage"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function PageFallback() {
  return (
    <div className="p-4 space-y-3">
      <Skeleton className="h-12 w-2/3" />
      <Skeleton className="h-20" />
      <Skeleton className="h-20" />
      <Skeleton className="h-20" />
    </div>
  );
}

function LiveNotifications() {
  useLiveNotifications();
  return null;
}

export function App() {
  useEffect(() => {
    initTelegram();
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <PinGate>
          <LiveNotifications />
          <BrowserRouter>
            <div className="min-h-full">
              <Suspense fallback={<PageFallback />}>
                <Routes>
                  <Route path="/" element={<Navigate to="/search" replace />} />
                  <Route path="/search" element={<SearchPage />} />
                  <Route path="/search/categories" element={<CategoriesPage />} />
                  <Route path="/search/categories/:slug" element={<CategoriesPage />} />
                  <Route path="/u/:username" element={<UserProfilePage />} />
                  <Route path="/deals" element={<DealsPage />} />
                  <Route path="/deals/new" element={<CreateDealPage />} />
                  <Route path="/deals/:id" element={<DealDetailPage />} />
                  <Route path="/help" element={<HelpPage />} />
                  <Route path="/notifications" element={<NotificationsPage />} />
                  <Route path="/profile" element={<ProfilePage />} />
                  <Route path="/profile/services/new" element={<AddServicePage />} />
                  <Route path="/profile/deposit" element={<DepositPage />} />
                  <Route path="/wallet" element={<WalletPage />} />
                  <Route path="/wallet/:code" element={<WalletCurrencyPage />} />
                  <Route path="*" element={<Navigate to="/search" replace />} />
                </Routes>
              </Suspense>
              <BottomNav />
            </div>
          </BrowserRouter>
        </PinGate>
      </ToastProvider>
    </QueryClientProvider>
  );
}
