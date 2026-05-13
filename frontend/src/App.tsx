import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
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
const SupportPage = lazy(() => import("@/pages/help/HelpPage"));
const NotificationsPage = lazy(() => import("@/pages/notifications/NotificationsPage"));
const NotificationDetailPage = lazy(() => import("@/pages/notifications/NotificationDetailPage"));
const ProfilePage = lazy(() => import("@/pages/profile/ProfilePage"));
const AddServicePage = lazy(() => import("@/pages/profile/AddServicePage"));
const AddForumPage = lazy(() => import("@/pages/profile/AddForumPage"));
const SettingsPage = lazy(() => import("@/pages/profile/SettingsPage"));
const DepositPage = lazy(() => import("@/pages/profile/DepositPage"));
const AccountTransferPage = lazy(() => import("@/pages/profile/AccountTransferPage"));
const WalletPage = lazy(() => import("@/pages/wallet/WalletPage"));
const WalletDepositPage = lazy(() => import("@/pages/wallet/WalletDepositPage"));
const WalletWithdrawPage = lazy(() => import("@/pages/wallet/WalletWithdrawPage"));
const WalletCurrencyPage = lazy(() => import("@/pages/wallet/WalletCurrencyPage"));
const ServiceDetailPage = lazy(() => import("@/pages/search/ServiceDetailPage"));
const ArbitrationPage = lazy(() => import("@/pages/arbitration/ArbitrationPage"));
const DealPaymentPage = lazy(() => import("@/pages/deals/DealPaymentPage"));
const PinResetPage = lazy(() => import("@/pages/pin/PinResetPage"));

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

function RedirectUser() {
  const { username } = useParams<{ username: string }>();
  return <Navigate to={`/users/${username ?? ""}`} replace />;
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
            <div className="min-h-full app-container">
              <Suspense fallback={<PageFallback />}>
                <Routes>
                  <Route path="/" element={<Navigate to="/search" replace />} />
                  <Route path="/search" element={<SearchPage />} />
                  <Route path="/search/categories" element={<CategoriesPage />} />
                  <Route path="/search/categories/:slug" element={<CategoriesPage />} />
                  <Route path="/users/:username" element={<UserProfilePage />} />
                  <Route path="/services/:id" element={<ServiceDetailPage />} />
                  <Route path="/deals" element={<DealsPage />} />
                  <Route path="/deals/new" element={<CreateDealPage />} />
                  <Route path="/create-deal/:username" element={<CreateDealPage />} />
                  <Route path="/deals/:id" element={<DealDetailPage />} />
                  <Route path="/deals/:id/payment" element={<DealPaymentPage />} />
                  <Route path="/support" element={<SupportPage />} />
                  <Route path="/notifications" element={<NotificationsPage />} />
                  <Route path="/notifications/:id" element={<NotificationDetailPage />} />
                  <Route path="/profile" element={<ProfilePage />} />
                  <Route path="/profile/add-service" element={<AddServicePage />} />
                  <Route path="/profile/add-forum" element={<AddForumPage />} />
                  <Route path="/profile/settings" element={<SettingsPage />} />
                  <Route path="/deposit" element={<DepositPage />} />
                  <Route path="/deposit/:id" element={<DepositPage />} />
                  <Route path="/change-account" element={<AccountTransferPage />} />
                  <Route path="/pin-reset" element={<PinResetPage />} />
                  <Route path="/arbitration" element={<ArbitrationPage />} />
                  <Route path="/wallet" element={<WalletPage />} />
                  <Route path="/wallet/deposit" element={<WalletDepositPage />} />
                  <Route path="/wallet/withdraw" element={<WalletWithdrawPage />} />
                  <Route path="/wallet/:code" element={<WalletCurrencyPage />} />
                  {/* Backwards-compatible redirects from the pre-Continental routes. */}
                  <Route path="/help" element={<Navigate to="/support" replace />} />
                  <Route path="/u/:username" element={<RedirectUser />} />
                  <Route path="/profile/services/new" element={<Navigate to="/profile/add-service" replace />} />
                  <Route path="/profile/deposit" element={<Navigate to="/deposit" replace />} />
                  <Route path="/profile/transfer" element={<Navigate to="/change-account" replace />} />
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
