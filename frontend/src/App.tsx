import { QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { MaintenanceBanner } from "@/components/MaintenanceBanner";
import { MinimizeButton } from "@/components/MinimizeButton";
import { PinGate } from "@/components/PinGate";
import { BottomNav } from "@/components/layout/BottomNav";
import { Skeleton } from "@/components/ui/Skeleton";
import { ToastProvider } from "@/components/ui/Toast";
import { installDevtoolsGuard } from "@/lib/devtoolsGuard";
import { useLiveNotifications } from "@/lib/useLiveNotifications";
import { queryClient } from "@/lib/queryClient";
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
const AccountTransferPage = lazy(() => import("@/pages/profile/AccountTransferPage"));
const WalletPage = lazy(() => import("@/pages/wallet/WalletPage"));
const WalletDepositPage = lazy(() => import("@/pages/wallet/WalletDepositPage"));
const WalletTrustDepositPage = lazy(
  () => import("@/pages/wallet/WalletTrustDepositPage"),
);
const WalletWithdrawPage = lazy(() => import("@/pages/wallet/WalletWithdrawPage"));
const WalletCurrencyPage = lazy(() => import("@/pages/wallet/WalletCurrencyPage"));
const ServiceDetailPage = lazy(() => import("@/pages/search/ServiceDetailPage"));
const ArbitrationPage = lazy(() => import("@/pages/arbitration/ArbitrationPage"));
const DealPaymentPage = lazy(() => import("@/pages/deals/DealPaymentPage"));
const PinResetPage = lazy(() => import("@/pages/pin/PinResetPage"));
const AdminDashboardPage = lazy(() => import("@/pages/admin/AdminDashboardPage"));
const AdminUsersPage = lazy(() => import("@/pages/admin/AdminUsersPage"));
const AdminUserDetailPage = lazy(() => import("@/pages/admin/AdminUserDetailPage"));
const AdminDealsPage = lazy(() => import("@/pages/admin/AdminDealsPage"));
const AdminDealDetailPage = lazy(() => import("@/pages/admin/AdminDealDetailPage"));
const AdminArbitrationPage = lazy(() => import("@/pages/admin/AdminArbitrationPage"));
const AdminWalletsPage = lazy(() => import("@/pages/admin/AdminWalletsPage"));
const AdminDepositsPage = lazy(() => import("@/pages/admin/AdminDepositsPage"));
const AdminWithdrawalsPage = lazy(() => import("@/pages/admin/AdminWithdrawalsPage"));
const AdminTreasuryPage = lazy(() => import("@/pages/admin/AdminTreasuryPage"));
const AdminSettingsPage = lazy(() => import("@/pages/admin/AdminSettingsPage"));
const AdminBroadcastsPage = lazy(() => import("@/pages/admin/AdminBroadcastsPage"));
const AdminAnalyticsPage = lazy(() => import("@/pages/admin/AdminAnalyticsPage"));
const AdminTaxonomyPage = lazy(() => import("@/pages/admin/AdminTaxonomyPage"));
const AdminSystemPage = lazy(() => import("@/pages/admin/AdminSystemPage"));
const AdminAuditPage = lazy(() => import("@/pages/admin/AdminAuditPage"));
const AdminTwoFactorPage = lazy(() => import("@/pages/admin/AdminTwoFactorPage"));

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

/**
 * Dev-only crash trigger — drives the ``ErrorBoundary`` overlay end-to-end.
 *
 * Mounted at ``/__dev/crash`` inside the ``import.meta.env.DEV`` branch
 * below so the route is only registered when Vite is running ``dev``;
 * production builds replace ``import.meta.env.DEV`` with the literal
 * ``false``, dead-code-eliminate the entire ``<Route>`` JSX, and tree-
 * shake this function out of the shipped bundle.
 *
 * The Playwright suite (``frontend/e2e/error-boundary.spec.ts``) needs
 * a deterministic way to force a render-time throw without relying on
 * brittle malformed-API tricks or Vite chunk-load internals; this
 * route does exactly that and nothing else.
 */
function DevCrashRoute(): null {
  throw new Error("Dev-only forced render crash for ErrorBoundary e2e tests");
}

export function App() {
  useEffect(() => {
    initTelegram();
    // Lock down devtools shortcuts + right-click. The Mini App is a
    // kiosk-style window (fullscreen on both PC and mobile per the
    // product spec), so F12 / Ctrl+Shift+I / view-source / right-click
    // are all preventDefault'd here. Returns a cleanup function so
    // React Strict Mode double-mounts don't leave duplicate listeners.
    return installDevtoolsGuard();
  }, []);

  return (
    // V12-I5 — outermost app-wide error boundary. Sits *above* every
    // provider so a render error inside ``QueryClientProvider`` /
    // ``ToastProvider`` / ``PinGate`` / ``BrowserRouter`` still surfaces
    // a recoverable overlay instead of React's blank-screen default.
    // The fallback intentionally uses pure Tailwind classes and no
    // context lookups so it remains paintable even when every provider
    // below it has failed to mount.
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <PinGate>
            <MaintenanceBanner />
            <BrowserRouter>
              {/* LiveNotifications must live *inside* BrowserRouter so
                  future toast-click handlers can call ``useNavigate``
                  to jump straight to ``/deals/:id`` etc. Outside the
                  router the hook is unreachable and we'd silently lose
                  the navigation. */}
              <LiveNotifications />
              <MinimizeButton />
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
                    {/* H-1 — legacy USD ``/deposit`` retired; redirect to the
                        multi-currency ``/wallet/deposit`` flow. */}
                    <Route path="/deposit" element={<Navigate to="/wallet/deposit" replace />} />
                    <Route path="/deposit/:id" element={<Navigate to="/wallet/deposit" replace />} />
                    <Route path="/change-account" element={<AccountTransferPage />} />
                    <Route path="/pin-reset" element={<PinResetPage />} />
                    <Route path="/arbitration" element={<ArbitrationPage />} />
                    <Route path="/wallet" element={<WalletPage />} />
                    <Route path="/wallet/deposit" element={<WalletDepositPage />} />
                    <Route
                      path="/wallet/trust-deposit"
                      element={<WalletTrustDepositPage />}
                    />
                    <Route path="/wallet/withdraw" element={<WalletWithdrawPage />} />
                    <Route path="/wallet/:code" element={<WalletCurrencyPage />} />
                    <Route path="/admin" element={<Navigate to="/admin/dashboard" replace />} />
                    <Route path="/admin/dashboard" element={<AdminDashboardPage />} />
                    <Route path="/admin/users" element={<AdminUsersPage />} />
                    <Route path="/admin/users/:id" element={<AdminUserDetailPage />} />
                    <Route path="/admin/deals" element={<AdminDealsPage />} />
                    <Route path="/admin/deals/:id" element={<AdminDealDetailPage />} />
                    <Route path="/admin/arbitration" element={<AdminArbitrationPage />} />
                    <Route path="/admin/wallets" element={<AdminWalletsPage />} />
                    <Route path="/admin/deposits" element={<AdminDepositsPage />} />
                    <Route path="/admin/withdrawals" element={<AdminWithdrawalsPage />} />
                    <Route path="/admin/treasury" element={<AdminTreasuryPage />} />
                    <Route path="/admin/settings" element={<AdminSettingsPage />} />
                    <Route path="/admin/broadcasts" element={<AdminBroadcastsPage />} />
                    <Route path="/admin/analytics" element={<AdminAnalyticsPage />} />
                    <Route path="/admin/taxonomy" element={<AdminTaxonomyPage />} />
                    <Route path="/admin/system" element={<AdminSystemPage />} />
                    <Route path="/admin/audit" element={<AdminAuditPage />} />
                    <Route path="/admin/2fa" element={<AdminTwoFactorPage />} />
                    {/* Dev-only render-throw target for the ErrorBoundary e2e
                        spec. Wrapped in ``import.meta.env.DEV`` so Vite tree-
                        shakes the entire route off production bundles. */}
                    {import.meta.env.DEV && (
                      <Route path="/__dev/crash" element={<DevCrashRoute />} />
                    )}
                    {/* Backwards-compatible redirects from the pre-Continental routes. */}
                    <Route path="/help" element={<Navigate to="/support" replace />} />
                    <Route path="/u/:username" element={<RedirectUser />} />
                    <Route path="/profile/services/new" element={<Navigate to="/profile/add-service" replace />} />
                    <Route path="/profile/deposit" element={<Navigate to="/wallet/deposit" replace />} />
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
    </ErrorBoundary>
  );
}
