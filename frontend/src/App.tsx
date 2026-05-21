import { QueryClientProvider } from "@tanstack/react-query";
import { Suspense, useEffect } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useParams,
} from "react-router-dom";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { MaintenanceBanner } from "@/components/MaintenanceBanner";
import { MinimizeButton } from "@/components/MinimizeButton";
import { PinGate } from "@/components/PinGate";
import { TelegramAvatarSync } from "@/components/TelegramAvatarSync";
import { TotpGate } from "@/components/TotpGate";
import { BottomNav } from "@/components/layout/BottomNav";
import { Skeleton } from "@/components/ui/Skeleton";
import { ToastProvider } from "@/components/ui/Toast";
import { installDevtoolsGuard } from "@/lib/devtoolsGuard";
import { lazyWithRetry } from "@/lib/lazyWithRetry";
import { useLiveNotifications } from "@/lib/useLiveNotifications";
import { queryClient } from "@/lib/queryClient";
import { initTelegram } from "@/lib/tg";

// ``lazyWithRetry`` (V12-Ix) wraps ``React.lazy`` with a one-shot
// hard-reload on chunk-load failures. The previous bare ``lazy(() =>
// import(...))`` paths surfaced ``Failed to fetch dynamically imported
// module: …/DealDetailPage.tsx`` straight into the ErrorBoundary
// after the Vite dev server was restarted (or a fresh production
// build replaced hashed chunk filenames the open tab still cached);
// the wrapper forces a single ``location.reload()`` so the browser
// fetches the up-to-date ``index.html`` and the next mount resolves.
const SearchPage = lazyWithRetry(() => import("@/pages/search/SearchPage"), "SearchPage");
const CategoriesPage = lazyWithRetry(() => import("@/pages/search/CategoriesPage"), "CategoriesPage");
const UserProfilePage = lazyWithRetry(() => import("@/pages/search/UserProfilePage"), "UserProfilePage");
const DealsPage = lazyWithRetry(() => import("@/pages/deals/DealsPage"), "DealsPage");
const DealDetailPage = lazyWithRetry(() => import("@/pages/deals/DealDetailPage"), "DealDetailPage");
const CreateDealPage = lazyWithRetry(() => import("@/pages/deals/CreateDealPage"), "CreateDealPage");
const SupportPage = lazyWithRetry(() => import("@/pages/help/HelpPage"), "HelpPage");
const NotificationsPage = lazyWithRetry(() => import("@/pages/notifications/NotificationsPage"), "NotificationsPage");
const NotificationDetailPage = lazyWithRetry(() => import("@/pages/notifications/NotificationDetailPage"), "NotificationDetailPage");
const ProfilePage = lazyWithRetry(() => import("@/pages/profile/ProfilePage"), "ProfilePage");
const AddServicePage = lazyWithRetry(() => import("@/pages/profile/AddServicePage"), "AddServicePage");
const AddForumPage = lazyWithRetry(() => import("@/pages/profile/AddForumPage"), "AddForumPage");
const SettingsPage = lazyWithRetry(() => import("@/pages/profile/SettingsPage"), "SettingsPage");
const AccountTransferPage = lazyWithRetry(() => import("@/pages/profile/AccountTransferPage"), "AccountTransferPage");
const WalletPage = lazyWithRetry(() => import("@/pages/wallet/WalletPage"), "WalletPage");
const WalletDepositPage = lazyWithRetry(() => import("@/pages/wallet/WalletDepositPage"), "WalletDepositPage");
const WalletTrustDepositPage = lazyWithRetry(
  () => import("@/pages/wallet/WalletTrustDepositPage"),
  "WalletTrustDepositPage",
);
const WalletWithdrawPage = lazyWithRetry(() => import("@/pages/wallet/WalletWithdrawPage"), "WalletWithdrawPage");
const WalletCurrencyPage = lazyWithRetry(() => import("@/pages/wallet/WalletCurrencyPage"), "WalletCurrencyPage");
const ServiceDetailPage = lazyWithRetry(() => import("@/pages/search/ServiceDetailPage"), "ServiceDetailPage");
const ArbitrationPage = lazyWithRetry(() => import("@/pages/arbitration/ArbitrationPage"), "ArbitrationPage");
const PinResetPage = lazyWithRetry(() => import("@/pages/pin/PinResetPage"), "PinResetPage");
const AdminDashboardPage = lazyWithRetry(() => import("@/pages/admin/AdminDashboardPage"), "AdminDashboardPage");
const AdminUsersPage = lazyWithRetry(() => import("@/pages/admin/AdminUsersPage"), "AdminUsersPage");
const AdminUserDetailPage = lazyWithRetry(() => import("@/pages/admin/AdminUserDetailPage"), "AdminUserDetailPage");
const AdminDealsPage = lazyWithRetry(() => import("@/pages/admin/AdminDealsPage"), "AdminDealsPage");
const AdminDealDetailPage = lazyWithRetry(() => import("@/pages/admin/AdminDealDetailPage"), "AdminDealDetailPage");
const AdminArbitrationPage = lazyWithRetry(() => import("@/pages/admin/AdminArbitrationPage"), "AdminArbitrationPage");
const AdminWalletsPage = lazyWithRetry(() => import("@/pages/admin/AdminWalletsPage"), "AdminWalletsPage");
const AdminDepositsPage = lazyWithRetry(() => import("@/pages/admin/AdminDepositsPage"), "AdminDepositsPage");
const AdminWithdrawalsPage = lazyWithRetry(() => import("@/pages/admin/AdminWithdrawalsPage"), "AdminWithdrawalsPage");
const AdminTreasuryPage = lazyWithRetry(() => import("@/pages/admin/AdminTreasuryPage"), "AdminTreasuryPage");
const AdminSettingsPage = lazyWithRetry(() => import("@/pages/admin/AdminSettingsPage"), "AdminSettingsPage");
const AdminBroadcastsPage = lazyWithRetry(() => import("@/pages/admin/AdminBroadcastsPage"), "AdminBroadcastsPage");
const AdminAnalyticsPage = lazyWithRetry(() => import("@/pages/admin/AdminAnalyticsPage"), "AdminAnalyticsPage");
const AdminTaxonomyPage = lazyWithRetry(() => import("@/pages/admin/AdminTaxonomyPage"), "AdminTaxonomyPage");
const AdminSystemPage = lazyWithRetry(() => import("@/pages/admin/AdminSystemPage"), "AdminSystemPage");
const AdminAuditPage = lazyWithRetry(() => import("@/pages/admin/AdminAuditPage"), "AdminAuditPage");
const AdminTwoFactorPage = lazyWithRetry(() => import("@/pages/admin/AdminTwoFactorPage"), "AdminTwoFactorPage");

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

/**
 * Reset the document scroll to the top on every route change.
 *
 * Without this, a user who scrolled to the bottom of, say, the admin
 * dashboard and then tapped "Таксономия" would land on
 * ``/admin/taxonomy`` with the browser scroll position still pinned
 * at the bottom — the page renders correctly but the user sees the
 * footer of the new page until they manually scroll back up. The
 * user surfaced this as "кнопки валюта и таксономия ведут … в самый
 * низ окна а не на верх".
 */
function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    try {
      window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    } catch {
      window.scrollTo(0, 0);
    }
  }, [pathname]);
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
            <TelegramAvatarSync />
            <MaintenanceBanner />
            <BrowserRouter>
              {/* LiveNotifications must live *inside* BrowserRouter so
                  future toast-click handlers can call ``useNavigate``
                  to jump straight to ``/deals/:id`` etc. Outside the
                  router the hook is unreachable and we'd silently lose
                  the navigation. */}
              <LiveNotifications />
              <ScrollToTop />
              <TotpGate />
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
