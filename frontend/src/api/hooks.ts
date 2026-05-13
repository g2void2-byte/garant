import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  AccountTransferConfirmDto,
  AccountTransferStartDto,
  AccountTransferStatusDto,
  CategoryDto,
  CurrencyDto,
  DealDto,
  DealMessageDto,
  DealMessagesPageDto,
  DealUnreadDto,
  DealUnreadTotalDto,
  DepositDto,
  InvoiceDto,
  NotificationCountersDto,
  NotificationDto,
  PinResetRequestDto,
  PinStatusDto,
  PinTokenDto,
  ReviewDto,
  ServiceDto,
  SupportPersonDto,
  UserCardDto,
  WalletBalanceDto,
  WalletDepositDto,
  WalletWithdrawalDto,
} from "./types";

export function useMe() {
  return useQuery<UserCardDto>({
    queryKey: ["me"],
    queryFn: () => api.get("api/me").json(),
    staleTime: 30_000,
  });
}

export function useUpdateMe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<{ description: string; banner_url: string | null; forums: any[] }>) =>
      api.patch("api/me", { json: body }).json<UserCardDto>(),
    onSuccess: (data) => {
      qc.setQueryData(["me"], data);
    },
  });
}

export function useCategories() {
  return useQuery<CategoryDto[]>({
    queryKey: ["categories"],
    queryFn: () => api.get("api/categories").json(),
    staleTime: 5 * 60_000,
  });
}

export function useServices(params: { category?: string; q?: string; owner?: string } = {}) {
  const searchParams: Record<string, string> = {};
  if (params.category) searchParams.category = params.category;
  if (params.q) searchParams.q = params.q;
  if (params.owner) searchParams.owner = params.owner;
  return useQuery<ServiceDto[]>({
    queryKey: ["services", params],
    queryFn: () => api.get("api/services", { searchParams }).json(),
    staleTime: 30_000,
  });
}

export function useCreateService() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { category_slug: string; title: string; description: string; price: number }) =>
      api.post("api/services", { json: body }).json<ServiceDto>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["services"] });
      qc.invalidateQueries({ queryKey: ["categories"] });
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

export function useDeleteService() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`api/services/${id}`).json(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["services"] });
    },
  });
}

export function useUsers(params: { q?: string; filter?: string } = {}) {
  const searchParams: Record<string, string> = {};
  if (params.q) searchParams.q = params.q;
  if (params.filter) searchParams.filter = params.filter;
  return useQuery<UserCardDto[]>({
    queryKey: ["users", params],
    queryFn: () => api.get("api/users", { searchParams }).json(),
    staleTime: 15_000,
  });
}

export function useUser(username: string | undefined) {
  return useQuery<UserCardDto>({
    queryKey: ["user", username],
    queryFn: () => api.get(`api/users/${username}`).json(),
    enabled: !!username,
  });
}

export function useDeals(params: { role?: string; status?: string } = {}) {
  const searchParams: Record<string, string> = {};
  if (params.role) searchParams.role = params.role;
  if (params.status) searchParams.status = params.status;
  return useQuery<DealDto[]>({
    queryKey: ["deals", params],
    queryFn: () => api.get("api/deals", { searchParams }).json(),
    staleTime: 15_000,
  });
}

export function useDeal(id: number | undefined) {
  return useQuery<DealDto>({
    queryKey: ["deal", id],
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
      qc.invalidateQueries({ queryKey: ["deals"] });
      qc.invalidateQueries({ queryKey: ["deal"] });
      qc.invalidateQueries({ queryKey: ["wallet"] });
    },
  });
}

export function useCreateDeal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      counterparty: string;
      role: "buyer" | "seller";
      sum: number;
      description: string;
      pay_comission: "buyer" | "seller";
      currency_code: string;
    }) => api.post("api/deals", { json: body }).json<DealDto>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["deals"] });
      qc.invalidateQueries({ queryKey: ["wallet"] });
    },
  });
}

export function useReviews(username: string | undefined) {
  return useQuery<ReviewDto[]>({
    queryKey: ["reviews", username],
    queryFn: () => api.get("api/reviews", { searchParams: { user: username! } }).json(),
    enabled: !!username,
  });
}

export function useCreateReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { target_username: string; rating: number; text: string; deal_id?: number }) =>
      api.post("api/reviews", { json: body }).json<ReviewDto>(),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ["reviews", vars.target_username] });
      qc.invalidateQueries({ queryKey: ["user", vars.target_username] });
    },
  });
}

export function useNotifications(type?: string) {
  return useQuery<NotificationDto[]>({
    queryKey: ["notifications", type ?? "all"],
    queryFn: () =>
      api.get("api/notifications", { searchParams: type ? { type } : {} }).json(),
    refetchInterval: 30_000,
  });
}

export function useNotificationCounters() {
  return useQuery<NotificationCountersDto>({
    queryKey: ["notifications", "counters"],
    queryFn: () => api.get("api/notifications/counters").json(),
    refetchInterval: 30_000,
  });
}

export function useMarkNotificationRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.post(`api/notifications/${id}/read`).json(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

export function useMarkAllRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post("api/notifications/read-all").json(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
}

export function useAdmins() {
  return useQuery<SupportPersonDto[]>({
    queryKey: ["support", "admins"],
    queryFn: () => api.get("api/support/admins").json(),
    staleTime: 5 * 60_000,
  });
}

export function useArbiters() {
  return useQuery<SupportPersonDto[]>({
    queryKey: ["support", "arbiters"],
    queryFn: () => api.get("api/support/arbiters").json(),
    staleTime: 5 * 60_000,
  });
}

export function useDeposits() {
  return useQuery<DepositDto[]>({
    queryKey: ["payments", "deposits"],
    queryFn: () => api.get("api/payments/deposit").json(),
    staleTime: 30_000,
  });
}

export function useCreateDepositInvoice() {
  return useMutation({
    mutationFn: (amount: number) =>
      api.post("api/payments/deposit/invoice", { json: { amount } }).json<InvoiceDto>(),
  });
}

export function useCreateDeposit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (amount: number) => api.post("api/payments/deposit", { json: { amount } }).json<DepositDto>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["payments"] });
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

export function useWithdraw() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (amount: number) => api.post("api/payments/withdraw", { json: { amount } }).json(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }),
  });
}

// ── PIN ─────────────────────────────────────────────────

export function usePinStatus() {
  return useQuery<PinStatusDto>({
    queryKey: ["pin", "status"],
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
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pin"] }),
  });
}

export function useCheckPin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (pin: string) =>
      api.post("api/pin/check", { json: { pin } }).json<PinTokenDto>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pin"] }),
  });
}

export function useChangePin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { old_pin: string; new_pin: string }) =>
      api.post("api/pin/change", { json: body }).json<PinTokenDto>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pin"] }),
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
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pin"] }),
  });
}

// ── Deal chat (PR-4) ───────────────────────────────

export function useDealMessages(dealId: number | undefined) {
  return useQuery<DealMessagesPageDto>({
    queryKey: ["deals", dealId, "messages"],
    queryFn: () => api.get(`api/deals/${dealId}/messages`).json(),
    enabled: !!dealId,
    staleTime: 5_000,
  });
}

export function useSendDealMessage(dealId: number | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (bodyText: string) =>
      api
        .post(`api/deals/${dealId}/messages`, { json: { body: bodyText } })
        .json<DealMessageDto>(),
    onSuccess: (msg) => {
      qc.setQueryData<DealMessagesPageDto>(
        ["deals", dealId, "messages"],
        (prev) => {
          if (!prev) return { items: [msg], unread: 0 };
          if (prev.items.some((it) => it.id === msg.id)) return prev;
          return { ...prev, items: [...prev.items, msg] };
        },
      );
    },
  });
}

export function useMarkDealMessagesRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (dealId: number) =>
      api.post(`api/deals/${dealId}/messages/read`).json<DealUnreadDto>(),
    onSuccess: (_data, dealId) => {
      qc.setQueryData<DealMessagesPageDto>(
        ["deals", dealId, "messages"],
        (prev) => (prev ? { ...prev, unread: 0 } : prev),
      );
      qc.invalidateQueries({ queryKey: ["chat", "unread-total"] });
    },
  });
}

export function useDealUnreadTotal() {
  return useQuery<DealUnreadTotalDto>({
    queryKey: ["chat", "unread-total"],
    queryFn: () => api.get("api/chat/unread-total").json(),
    staleTime: 10_000,
  });
}

// ── Account transfer (PR-CA) ───────────────────────────

export function useAccountTransferStatus() {
  return useQuery<AccountTransferStatusDto>({
    queryKey: ["account", "transfer", "status"],
    queryFn: () => api.get("api/account/transfer/status").json(),
    refetchInterval: 30_000,
  });
}

export function useStartAccountTransfer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post("api/account/transfer/start").json<AccountTransferStartDto>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["account", "transfer"] }),
  });
}

export function useCancelAccountTransfer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post("api/account/transfer/cancel").json<AccountTransferStatusDto>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["account", "transfer"] }),
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
    queryKey: ["wallet", "currencies"],
    queryFn: () => api.get("api/wallet/currencies").json(),
    staleTime: 60 * 60_000,
  });
}

export function useWalletBalances() {
  return useQuery<WalletBalanceDto[]>({
    queryKey: ["wallet", "balances"],
    queryFn: () => api.get("api/wallet/balances").json(),
    staleTime: 15_000,
  });
}

export function useWalletDeposits() {
  return useQuery<WalletDepositDto[]>({
    queryKey: ["wallet", "deposits"],
    queryFn: () => api.get("api/wallet/deposits").json(),
  });
}

export function useWalletDeposit(id: number | undefined) {
  return useQuery<WalletDepositDto>({
    queryKey: ["wallet", "deposit", id],
    queryFn: () => api.get(`api/wallet/deposits/${id}`).json(),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data?.status === "pending" ? 5_000 : false),
  });
}

export function useCreateWalletDeposit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { currency_code: string; amount: number }) =>
      api.post("api/wallet/deposits", { json: body }).json<WalletDepositDto>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wallet", "deposits"] });
      qc.invalidateQueries({ queryKey: ["wallet", "balances"] });
    },
  });
}

export function useWalletWithdrawals() {
  return useQuery<WalletWithdrawalDto[]>({
    queryKey: ["wallet", "withdrawals"],
    queryFn: () => api.get("api/wallet/withdrawals").json(),
  });
}

export function useCreateWalletWithdrawal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { currency_code: string; amount: number; address: string }) =>
      api.post("api/wallet/withdrawals", { json: body }).json<WalletWithdrawalDto>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wallet", "withdrawals"] });
      qc.invalidateQueries({ queryKey: ["wallet", "balances"] });
    },
  });
}
