import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { qk } from "./queryKeys";
import type {
  AccountTransferConfirmDto,
  AccountTransferStartDto,
  AccountTransferStatusDto,
  CategoryDto,
  CurrencyDto,
  DealDto,
  NotificationCountersDto,
  NotificationDto,
  PinResetRequestDto,
  PinStatusDto,
  PinTokenDto,
  ReviewDto,
  ServiceCommentDto,
  ServiceDetailDto,
  ServiceDto,
  SupportPersonDto,
  UserCardDto,
  WalletBalanceDto,
  WalletDepositDto,
  WalletWithdrawalDto,
} from "./types";

export function useMe() {
  return useQuery<UserCardDto>({
    queryKey: qk.me(),
    queryFn: () => api.get("api/me").json(),
    staleTime: 30_000,
  });
}

export interface MediaDto {
  id: number;
  kind: string;
  url: string;
  name: string;
  size: number;
  content_type: string;
  created_at?: string | null;
}

export function useUploadMedia() {
  return useMutation({
    mutationFn: async ({ kind, file }: { kind: string; file: File }) => {
      const form = new FormData();
      form.append("kind", kind);
      form.append("file", file);
      return api.post("api/media/upload", { body: form, timeout: 30_000 }).json<MediaDto>();
    },
  });
}

export function useUpdateMe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (
      body: Partial<{
        display_name: string;
        description: string;
        banner_url: string | null;
        photo_url: string | null;
        forums: { name: string; url: string }[];
        dm_deals: boolean;
        dm_deposits: boolean;
        dm_system: boolean;
        is_anonymous_deals: boolean;
        is_hidden_profile: boolean;
        // ISO-3166-1 alpha-2 code (uppercase). ``null`` explicitly
        // clears the column; omitting the key is a no-op.
        country: string | null;
      }>,
    ) => api.patch("api/me", { json: body }).json<UserCardDto>(),
    onSuccess: (data) => {
      qc.setQueryData(qk.me(), data);
      // V12-UI — when the *current* user updates their banner / avatar
      // / description / forums the public ``/api/users/{username}``
      // representation drifts too. Invalidate it so the next render
      // of ``UserProfilePage`` (for the same username) refetches and
      // doesn't show a stale banner.
      if (data.username) {
        qc.invalidateQueries({ queryKey: qk.user.detail(data.username) });
      }
      qc.invalidateQueries({ queryKey: qk.users.all() });
    },
  });
}

export function useCategories() {
  return useQuery<CategoryDto[]>({
    queryKey: qk.categories(),
    queryFn: () => api.get("api/categories").json(),
    staleTime: 5 * 60_000,
  });
}

export function useServices(
  params: { category?: string; q?: string; owner?: string; status?: string } = {},
) {
  const searchParams: Record<string, string> = {};
  if (params.category) searchParams.category = params.category;
  if (params.q) searchParams.q = params.q;
  if (params.owner) searchParams.owner = params.owner;
  if (params.status) searchParams.status = params.status;
  return useQuery<ServiceDto[]>({
    queryKey: qk.services.list(params),
    queryFn: () => api.get("api/services", { searchParams }).json(),
    staleTime: 30_000,
  });
}

export function useUpdateService() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: number;
      body: Partial<{
        title: string;
        description: string;
        price: number;
        status: string;
        photo_urls: string[];
      }>;
    }) => api.patch(`api/services/${id}`, { json: body }).json<ServiceDto>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.services.all() });
    },
  });
}

export function useCreateService() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      category_slug: string;
      title: string;
      description: string;
      price: number;
      photo_urls?: string[];
    }) => api.post("api/services", { json: body }).json<ServiceDto>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.services.all() });
      qc.invalidateQueries({ queryKey: qk.categories() });
      qc.invalidateQueries({ queryKey: qk.me() });
    },
  });
}

export function useDeleteService() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`api/services/${id}`).json(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.services.all() });
    },
  });
}

export function useServiceDetail(id: number | undefined) {
  return useQuery<ServiceDetailDto>({
    queryKey: qk.service.detail(id),
    queryFn: () => api.get(`api/services/${id}`).json(),
    enabled: !!id,
    staleTime: 30_000,
  });
}

export function useServiceComments(id: number | undefined) {
  return useQuery<ServiceCommentDto[]>({
    queryKey: qk.service.comments(id),
    queryFn: () => api.get(`api/services/${id}/comments`).json(),
    enabled: !!id,
    staleTime: 15_000,
  });
}

export function useCreateServiceComment(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { text: string; rating: number | null }) =>
      api.post(`api/services/${id}/comments`, { json: body }).json<ServiceCommentDto>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.service.comments(id) });
      qc.invalidateQueries({ queryKey: qk.service.detail(id) });
    },
  });
}

export function useDeleteServiceComment(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (commentId: number) =>
      api.delete(`api/services/${id}/comments/${commentId}`).json(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.service.comments(id) });
      qc.invalidateQueries({ queryKey: qk.service.detail(id) });
    },
  });
}

export interface UsersQueryParams {
  q?: string;
  filter?: string;
  rating?: string;
  deals?: string;
  deposit_min?: string;
  status?: string;
  reg_from?: string;
  reg_to?: string;
}

export function useUsers(params: UsersQueryParams = {}) {
  const searchParams: Record<string, string> = {};
  if (params.q) searchParams.q = params.q;
  if (params.filter) searchParams.filter = params.filter;
  if (params.rating) searchParams.rating = params.rating;
  if (params.deals) searchParams.deals = params.deals;
  if (params.deposit_min) searchParams.deposit_min = params.deposit_min;
  if (params.status) searchParams.status = params.status;
  if (params.reg_from) searchParams.reg_from = params.reg_from;
  if (params.reg_to) searchParams.reg_to = params.reg_to;
  return useQuery<UserCardDto[]>({
    queryKey: qk.users.list(params),
    queryFn: () => api.get("api/users", { searchParams }).json(),
    staleTime: 15_000,
  });
}

export function useUser(username: string | undefined) {
  return useQuery<UserCardDto>({
    queryKey: qk.user.detail(username),
    queryFn: () => api.get(`api/users/${username}`).json(),
    enabled: !!username,
  });
}

export function useDeals(params: { role?: string; status?: string } = {}) {
  const searchParams: Record<string, string> = {};
  if (params.role) searchParams.role = params.role;
  if (params.status) searchParams.status = params.status;
  return useQuery<DealDto[]>({
    queryKey: qk.deals.list(params),
    queryFn: () => api.get("api/deals", { searchParams }).json(),
    staleTime: 15_000,
  });
}

export function useDeal(id: number | undefined) {
  return useQuery<DealDto>({
    queryKey: qk.deal.detail(id),
    queryFn: () => api.get(`api/deals/${id}`).json(),
    enabled: !!id,
  });
}

export type DealActionPath =
  | "accept"
  | "decline"
  | "finish"
  | "cancel_request"
  | "cancel_request/revoke"
  | "cancel_request/accept"
  | "debate"
  | "resolve";

export interface DealMessageDto {
  id: number;
  deal_id: number;
  sender_id: number;
  sender_username: string | null;
  text: string;
  attachments: MediaDto[];
  created_at: string;
}

export function useDealMessages(dealId: number | undefined) {
  return useQuery<DealMessageDto[]>({
    queryKey: qk.deal.messages(dealId),
    queryFn: () => api.get(`api/deals/${dealId}/messages`).json(),
    enabled: !!dealId,
    staleTime: 10_000,
  });
}

export function useSendDealMessage(dealId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { text: string; attachments: number[] }) =>
      api.post(`api/deals/${dealId}/messages`, { json: body }).json<DealMessageDto>(),
    onSuccess: (msg) => {
      qc.setQueryData<DealMessageDto[] | undefined>(
        qk.deal.messages(dealId),
        (prev) => {
          if (!prev) return [msg];
          if (prev.some((m) => m.id === msg.id)) return prev;
          return [...prev, msg];
        },
      );
    },
  });
}

export function useDealAction(action: DealActionPath) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: number;
      body?: Record<string, unknown>;
    }) =>
      api
        .post(`api/deals/${id}/${action}`, body ? { json: body } : {})
        .json<DealDto>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.deals.all() });
      qc.invalidateQueries({ queryKey: qk.deal.all() });
      qc.invalidateQueries({ queryKey: qk.wallet.all() });
    },
  });
}

export function useCreateDeal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      counterparty: string;
      role: "buyer" | "seller";
      amount: number;
      description: string;
      pay_comission: "buyer" | "seller";
      currency_code: string;
    }) => api.post("api/deals", { json: body }).json<DealDto>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.deals.all() });
      qc.invalidateQueries({ queryKey: qk.wallet.all() });
    },
  });
}

export function useReviews(username: string | undefined) {
  return useQuery<ReviewDto[]>({
    queryKey: qk.reviews.forUser(username),
    queryFn: () => api.get("api/reviews", { searchParams: { user: username! } }).json(),
    enabled: !!username,
  });
}

export function useCreateReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { target_username: string; rating: number; text: string; deal_id: number }) =>
      api.post("api/reviews", { json: body }).json<ReviewDto>(),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: qk.reviews.forUser(vars.target_username) });
      qc.invalidateQueries({ queryKey: qk.user.detail(vars.target_username) });
    },
  });
}

export function useNotifications(type?: string) {
  return useQuery<NotificationDto[]>({
    queryKey: qk.notifications.list(type),
    queryFn: () =>
      api.get("api/notifications", { searchParams: type ? { type } : {} }).json(),
    refetchInterval: 30_000,
  });
}

export function useNotification(id: number | undefined) {
  return useQuery<NotificationDto>({
    queryKey: qk.notifications.detail(id),
    queryFn: () => api.get(`api/notifications/${id}`).json(),
    enabled: typeof id === "number" && Number.isFinite(id),
  });
}

export function useNotificationCounters() {
  return useQuery<NotificationCountersDto>({
    queryKey: qk.notifications.counters(),
    queryFn: () => api.get("api/notifications/counters").json(),
    refetchInterval: 30_000,
  });
}

export function useMarkNotificationRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.post(`api/notifications/${id}/read`).json(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.notifications.all() });
    },
  });
}

export function useMarkAllRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post("api/notifications/read-all").json(),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.notifications.all() }),
  });
}

export function useAdmins() {
  return useQuery<SupportPersonDto[]>({
    queryKey: qk.support.admins(),
    queryFn: () => api.get("api/support/admins").json(),
    staleTime: 5 * 60_000,
  });
}

export function useArbiters() {
  return useQuery<SupportPersonDto[]>({
    queryKey: qk.support.arbiters(),
    queryFn: () => api.get("api/support/arbiters").json(),
    staleTime: 5 * 60_000,
  });
}

// H-1 — legacy USD ``Invoice`` endpoints retired
// (``GET /api/payments/deposit``, ``POST /api/payments/deposit``,
// ``POST /api/payments/deposit/invoice``,
// ``GET /api/payments/deposit/invoice/{id}``). Use ``useWalletDeposits``
// / ``useCreateWalletDeposit`` for the multi-currency flow.

// ── PIN ─────────────────────────────────────────────────

export function usePinStatus() {
  return useQuery<PinStatusDto>({
    queryKey: qk.pin.status(),
    queryFn: () => api.get("api/pin/status").json(),
    staleTime: 0,
    refetchOnMount: true,
  });
}

export function useSetupPin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (pin: string) =>
      api.post("api/pin/setup", { json: { pin } }).json<PinTokenDto>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.pin.all() }),
  });
}

export function useCheckPin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (pin: string) =>
      api.post("api/pin/check", { json: { pin } }).json<PinTokenDto>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.pin.all() }),
  });
}

export function useChangePin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { old_pin: string; new_pin: string }) =>
      api.post("api/pin/change", { json: body }).json<PinTokenDto>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.pin.all() }),
  });
}

export function useRequestPinReset() {
  return useMutation({
    mutationFn: () => api.post("api/pin/reset/request").json<PinResetRequestDto>(),
  });
}

export function useConfirmPinReset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { code: string; new_pin: string }) =>
      api.post("api/pin/reset/confirm", { json: body }).json<PinTokenDto>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.pin.all() }),
  });
}

// ── Account transfer (PR-CA) ───────────────────────────

export function useAccountTransferStatus() {
  return useQuery<AccountTransferStatusDto>({
    queryKey: qk.account.transfer.status(),
    queryFn: () => api.get("api/account/transfer/status").json(),
    refetchInterval: 30_000,
  });
}

export function useStartAccountTransfer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post("api/account/transfer/start").json<AccountTransferStartDto>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.account.transfer.all() }),
  });
}

export function useCancelAccountTransfer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post("api/account/transfer/cancel").json<AccountTransferStatusDto>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.account.transfer.all() }),
  });
}

export function useConfirmAccountTransfer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) =>
      api
        .post("api/account/transfer/confirm", { json: { code } })
        .json<AccountTransferConfirmDto>(),
    onSuccess: () => {
      qc.invalidateQueries();
    },
  });
}

// ── Wallet ──────────────────────────────────────────────

export function useCurrencies() {
  return useQuery<CurrencyDto[]>({
    queryKey: qk.wallet.currencies(),
    queryFn: () => api.get("api/wallet/currencies").json(),
    staleTime: 60 * 60_000,
  });
}

export function useWalletBalances() {
  return useQuery<WalletBalanceDto[]>({
    queryKey: qk.wallet.balances(),
    queryFn: () => api.get("api/wallet/balances").json(),
    staleTime: 15_000,
  });
}

export function useWalletDeposits() {
  return useQuery<WalletDepositDto[]>({
    queryKey: qk.wallet.deposits(),
    queryFn: () => api.get("api/wallet/deposits").json(),
  });
}

export function useWalletDeposit(id: number | undefined) {
  return useQuery<WalletDepositDto>({
    queryKey: qk.wallet.deposit(id),
    queryFn: () => api.get(`api/wallet/deposits/${id}`).json(),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data?.status === "pending" ? 5_000 : false),
  });
}

// ``purpose`` follows ``WalletDepositDto.purpose`` — ``"wallet"``
// (default, credits ``UserBalance``) or ``"trust"`` (credits
// ``User.trust_deposit_balance``, no spend / withdraw path).
export interface CreateWalletDepositBody {
  currency_code: string;
  amount: number;
  purpose?: "wallet" | "trust";
  // Selects the upstream payment provider. Defaults to
  // ``"cryptobot"`` on the back-end when omitted; clients only need
  // to set this when offering the Crystalpay alternative.
  provider?: "cryptobot" | "crystalpay";
}

export function useCreateWalletDeposit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateWalletDepositBody) =>
      api.post("api/wallet/deposits", { json: body }).json<WalletDepositDto>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.wallet.deposits() });
      qc.invalidateQueries({ queryKey: qk.wallet.balances() });
      // Trust deposits credit ``User.trust_deposit_balance``, which
      // is rendered via ``UserCardDto.deposit`` from
      // ``GET /api/me`` — refresh that cache too so the wallet page's
      // trust-balance pill updates after a successful invoice.
      qc.invalidateQueries({ queryKey: qk.me() });
    },
  });
}

export function useWalletWithdrawals() {
  return useQuery<WalletWithdrawalDto[]>({
    queryKey: qk.wallet.withdrawals(),
    queryFn: () => api.get("api/wallet/withdrawals").json(),
  });
}

export function useCreateWalletWithdrawal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { currency_code: string; amount: number; address: string }) =>
      api.post("api/wallet/withdrawals", { json: body }).json<WalletWithdrawalDto>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.wallet.withdrawals() });
      qc.invalidateQueries({ queryKey: qk.wallet.balances() });
    },
  });
}
