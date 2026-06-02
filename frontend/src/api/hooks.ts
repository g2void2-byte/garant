import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { qk } from "./queryKeys";
import type {
  AccountTransferConfirmDto,
  AccountTransferStartDto,
  AccountTransferStatusDto,
  CategoryDto,
  CurrencyDto,
  DealCreateWithTopupResponseDto,
  DealDto,
  NotificationCountersDto,
  NotificationDto,
  PinResetRequestDto,
  PinStatusDto,
  PinTokenDto,
  PublicSettingsDto,
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

export function invalidateDealParticipantSideEffects(
  qc: ReturnType<typeof useQueryClient>,
) {
  qc.invalidateQueries({ queryKey: qk.wallet.all() });
  qc.invalidateQueries({ queryKey: qk.users.all() });
  qc.invalidateQueries({ queryKey: qk.user.all() });
  qc.invalidateQueries({ queryKey: qk.me() });
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
        // Items 13/15 — fiat currency code (``"USD"``, ``"UAH"``,
        // ``"RUB"``) for the new ProfilePage fiat-balance card.
        // ``null`` clears the column (UI falls back to USD).
        display_currency_code: string | null;
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
        qc.invalidateQueries({ queryKey: qk.reviews.forUser(data.username) });
      }
      qc.invalidateQueries({ queryKey: qk.users.all() });
      // M-27: ``is_hidden_profile`` and public profile fields are also
      // projected into service catalog/detail/comment and category badge
      // surfaces. Refresh those prefixes after profile edits so hiding
      // or revealing the current profile does not leave stale public rows.
      qc.invalidateQueries({ queryKey: qk.services.all() });
      qc.invalidateQueries({ queryKey: qk.service.all() });
      qc.invalidateQueries({ queryKey: qk.categories() });
    },
  });
}

export function useCategories(options: { enabled?: boolean } = {}) {
  return useQuery<CategoryDto[]>({
    queryKey: qk.categories(),
    queryFn: () => api.get("api/categories").json(),
    staleTime: 5 * 60_000,
    enabled: options.enabled ?? true,
  });
}

/**
 * ``GET /api/settings/public`` — read-only AppSettings subset. Used by
 * the deal-create form (commission preview) and the withdraw form
 * (auto-mode address-field toggle). The endpoint is unauth so we
 * intentionally do not retry; a network blip simply falls back to
 * the conservative defaults the consumer encodes locally.
 */
export function usePublicSettings() {
  return useQuery<PublicSettingsDto>({
    queryKey: qk.publicSettings(),
    queryFn: () => api.get("api/settings/public").json(),
    // The values rarely change (admin tunable) — a 5-minute stale
    // window is plenty and avoids hammering the endpoint on every
    // page mount.
    staleTime: 5 * 60_000,
    retry: false,
  });
}

// Audit v3 A-1 — fetch the approved forum names from the backend
// instead of duplicating the list in ``AddForumPage.tsx``. The
// response carries ``freeform_option`` (the "Другое" catch-all) so
// the UI can flag it for the "pick + type custom URL" affordance
// without hard-coding the spelling. The 30-minute ``staleTime`` is
// well past the page navigations a user makes in a session, and the
// HTTP response also carries ``Cache-Control: max-age=300`` for the
// browser layer below TanStack.
export interface ForumListDto {
  forums: string[];
  freeform_option: string;
}

export function useForums() {
  return useQuery<ForumListDto>({
    queryKey: qk.forums(),
    queryFn: () => api.get("api/forums").json(),
    staleTime: 30 * 60_000,
  });
}

export function useServices(
  params: { category?: string; q?: string; owner?: string; status?: string } = {},
  // Audit (continuation) L-2 — opt-in ``enabled`` gate. Callers that
  // pass ``owner: me?.username`` need a way to keep the query
  // dormant until ``me`` resolves; without it the first render
  // issues a list-all request that pollutes the cache.
  options: { enabled?: boolean } = {},
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
    enabled: options.enabled ?? true,
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
    onSuccess: (_service, vars) => {
      qc.invalidateQueries({ queryKey: qk.services.all() });
      qc.invalidateQueries({ queryKey: qk.categories() });
      qc.invalidateQueries({ queryKey: qk.service.detail(vars.id) });
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
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: qk.services.all() });
      qc.invalidateQueries({ queryKey: qk.categories() });
      qc.invalidateQueries({ queryKey: qk.service.detail(id) });
      qc.invalidateQueries({ queryKey: qk.service.comments(id) });
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
  status?: string;
  reg_from?: string;
  reg_to?: string;
  limit?: number;
  offset?: number;
  /**
   * When true, the request is for a counterparty picker (e.g.
   * /deals/new) — the backend bypasses the "min 1 deal" search gate
   * so brand-new users can still pick a counterparty.
   */
  picker?: boolean;
}

export function buildUsersSearchParams(params: UsersQueryParams = {}) {
  const searchParams: Record<string, string> = {};
  if (params.q) searchParams.q = params.q;
  if (params.filter) searchParams.filter = params.filter;
  if (params.rating) searchParams.rating = params.rating;
  if (params.deals) searchParams.deals = params.deals;
  if (params.status) searchParams.status = params.status;
  if (params.reg_from) searchParams.reg_from = params.reg_from;
  if (params.reg_to) searchParams.reg_to = params.reg_to;
  if (params.limit !== undefined) searchParams.limit = String(params.limit);
  if (params.offset !== undefined) searchParams.offset = String(params.offset);
  if (params.picker) searchParams.picker = "1";
  return searchParams;
}

export function useUsers(
  params: UsersQueryParams = {},
  options: { enabled?: boolean } = {},
) {
  const searchParams = buildUsersSearchParams(params);
  return useQuery<UserCardDto[]>({
    queryKey: qk.users.list(params),
    queryFn: () => api.get("api/users", { searchParams }).json(),
    staleTime: 15_000,
    enabled: options.enabled ?? true,
  });
}

export function useUser(username: string | undefined) {
  return useQuery<UserCardDto>({
    queryKey: qk.user.detail(username),
    queryFn: () => api.get(`api/users/${username}`).json(),
    enabled: !!username,
  });
}

export interface DealQueryParams {
  role?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

export function buildDealsSearchParams(params: DealQueryParams) {
  const searchParams: Record<string, string> = {};
  if (params.role && params.role !== "all") searchParams.role = params.role;
  if (params.status) searchParams.status = params.status;
  if (params.limit !== undefined) searchParams.limit = String(params.limit);
  if (params.offset !== undefined) searchParams.offset = String(params.offset);
  return searchParams;
}

export function useDeals(params: DealQueryParams = {}) {
  const searchParams = buildDealsSearchParams(params);
  return useQuery<DealDto[]>({
    queryKey: qk.deals.list(params),
    queryFn: () => api.get("api/deals", { searchParams }).json(),
    staleTime: 15_000,
  });
}

// Item 22 — once a deal lands in one of these statuses no further
// server-side state change is possible, so we stop the polling fallback
// to keep idle TMA sessions quiet.
const TERMINAL_DEAL_STATUSES = new Set([
  "completed",
  "cancelled",
  "cancelled_for_inactivity",
  "resolved_for_buyer",
  "resolved_for_seller",
]);

export function useDeal(id: number | undefined) {
  return useQuery<DealDto>({
    queryKey: qk.deal.detail(id),
    queryFn: () => api.get(`api/deals/${id}`).json(),
    enabled: !!id,
    // Item 22 — fallback poll for active deals so the UI eventually
    // catches a missed ``deal.updated`` WS frame (Telegram WebView
    // suspended, transient socket close, etc.). Terminal deals stop
    // polling so closed sessions don't generate background traffic.
    refetchInterval: (query) => {
      const data = query.state.data as DealDto | undefined;
      if (!data) return false;
      return TERMINAL_DEAL_STATUSES.has(data.status) ? false : 10_000;
    },
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

// Audit H2 — backend paginates ``GET /api/deals/{id}/messages`` with a
// ``limit`` (default 50, max 200) and a ``before_id`` cursor. The
// initial query fetches the newest page; ``useLoadOlderDealMessages``
// prepends the next older page to the same cache entry. Keeping a
// flat ``DealMessageDto[]`` cache (instead of paged ``InfiniteQuery``)
// preserves the existing append-on-WS / append-on-POST contract used
// by ``useLiveNotifications`` and ``useSendDealMessage``.
export const DEAL_MESSAGE_PAGE_SIZE = 50;

export function useDealMessages(dealId: number | undefined) {
  return useQuery<DealMessageDto[]>({
    queryKey: qk.deal.messages(dealId),
    queryFn: () =>
      api
        .get(`api/deals/${dealId}/messages`, {
          searchParams: { limit: DEAL_MESSAGE_PAGE_SIZE },
        })
        .json(),
    enabled: !!dealId,
    staleTime: 10_000,
  });
}

export function useLoadOlderDealMessages(dealId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (params: { beforeId: number; limit?: number }) => {
      const page = await api
        .get(`api/deals/${dealId}/messages`, {
          searchParams: {
            before_id: params.beforeId,
            limit: params.limit ?? DEAL_MESSAGE_PAGE_SIZE,
          },
        })
        .json<DealMessageDto[]>();
      qc.setQueryData<DealMessageDto[] | undefined>(
        qk.deal.messages(dealId),
        (prev) => {
          if (!prev) return page;
          const seen = new Set(prev.map((m) => m.id));
          const older = page.filter((m) => !seen.has(m.id));
          return [...older, ...prev];
        },
      );
      return page;
    },
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
      invalidateDealParticipantSideEffects(qc);
    },
  });
}

export function useCreateDeal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      counterparty: string;
      role: "buyer";
      amount: string;
      description: string;
      currency_code: string;
      payment_provider?: "cryptobot" | "crystalpay";
    }) => api.post("api/deals", { json: body }).json<DealDto>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.deals.all() });
      qc.invalidateQueries({ queryKey: qk.wallet.all() });
    },
  });
}

export function useCreateDealWithTopup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      counterparty: string;
      role: "buyer";
      amount: string;
      description: string;
      currency_code: string;
      payment_provider?: "cryptobot" | "crystalpay";
    }) => api.post("api/deals/with-topup", { json: body }).json<DealCreateWithTopupResponseDto>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.deals.all() });
      qc.invalidateQueries({ queryKey: qk.wallet.all() });
    },
  });
}

export function useCancelPendingTopup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.post(`api/deals/${id}/cancel-topup`).json<DealDto>(),
    onSuccess: (_deal, id) => {
      qc.invalidateQueries({ queryKey: qk.deals.all() });
      qc.invalidateQueries({ queryKey: qk.deal.detail(id) });
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
      qc.invalidateQueries({ queryKey: qk.users.all() });
    },
  });
}

export interface NotificationsQueryParams {
  type?: string;
  before_created_at?: string;
  before_id?: number;
  limit?: number;
}

export function buildNotificationsSearchParams(params: NotificationsQueryParams) {
  const searchParams: Record<string, string> = {};
  if (params.type) searchParams.type = params.type;
  if (params.before_created_at) searchParams.before_created_at = params.before_created_at;
  if (params.before_id !== undefined) searchParams.before_id = String(params.before_id);
  if (params.limit !== undefined) searchParams.limit = String(params.limit);
  return searchParams;
}

export function useNotifications(params: NotificationsQueryParams = {}) {
  const searchParams = buildNotificationsSearchParams(params);
  return useQuery<NotificationDto[]>({
    queryKey: qk.notifications.list(params),
    queryFn: () => api.get("api/notifications", { searchParams }).json(),
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

// Bug-13 — folds a notification into its cached representations.
// Walks every ``["notifications", ...]`` query and either flips a
// single id's ``is_read`` (single mark-read) or every unread one
// (mark-all). Counters are recomputed from the seen unread ids so the
// pill in ``BottomNav`` updates without waiting for the next refetch.
function applyReadToCaches(
  qc: ReturnType<typeof useQueryClient>,
  predicate: (n: NotificationDto) => boolean,
): { flippedByType: Record<string, number>; flippedTotal: number } {
  const flippedByType: Record<string, number> = {};
  let flippedTotal = 0;
  qc.setQueriesData<NotificationDto[] | undefined>(
    { queryKey: qk.notifications.all() },
    (prev) => {
      if (!Array.isArray(prev)) return prev;
      let changed = false;
      const next = prev.map((n) => {
        if (n.is_read || !predicate(n)) return n;
        changed = true;
        flippedByType[n.type] = (flippedByType[n.type] ?? 0) + 1;
        flippedTotal += 1;
        return { ...n, is_read: true };
      });
      return changed ? next : prev;
    },
  );
  return { flippedByType, flippedTotal };
}

function applyCountersDelta(
  qc: ReturnType<typeof useQueryClient>,
  flippedByType: Record<string, number>,
  flippedTotal: number,
) {
  qc.setQueryData<NotificationCountersDto | undefined>(
    qk.notifications.counters(),
    (prev) => {
      if (!prev) return prev;
      const dec = (key: keyof NotificationCountersDto) => {
        const delta = flippedByType[key as string] ?? 0;
        return Math.max(0, (prev[key] ?? 0) - delta);
      };
      return {
        ...prev,
        all: prev.all,
        deals: dec("deals"),
        deposits: dec("deposits"),
        system: dec("system"),
        unread: Math.max(0, (prev.unread ?? 0) - flippedTotal),
      };
    },
  );
}

export function useMarkNotificationRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.post(`api/notifications/${id}/read`).json(),
    // Bug-13 — optimistic update: flip the row + decrement counters
    // immediately so the bell badge in ``BottomNav`` and the unread
    // pip on the row disappear on click. ``onSettled`` re-invalidates
    // for consistency in case the optimistic delta drifted.
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: qk.notifications.all() });
      const listsSnapshot = qc.getQueriesData<NotificationDto[] | undefined>({
        queryKey: qk.notifications.all(),
      });
      const countersSnapshot = qc.getQueryData<NotificationCountersDto | undefined>(
        qk.notifications.counters(),
      );
      const { flippedByType, flippedTotal } = applyReadToCaches(
        qc,
        (n) => n.id === id,
      );
      applyCountersDelta(qc, flippedByType, flippedTotal);
      return { listsSnapshot, countersSnapshot };
    },
    onError: (_err, _id, ctx) => {
      if (!ctx) return;
      for (const [key, value] of ctx.listsSnapshot) {
        qc.setQueryData(key, value);
      }
      if (ctx.countersSnapshot) {
        qc.setQueryData(qk.notifications.counters(), ctx.countersSnapshot);
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: qk.notifications.all() });
    },
  });
}

export function useMarkAllRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post("api/notifications/read-all").json(),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: qk.notifications.all() });
      const listsSnapshot = qc.getQueriesData<NotificationDto[] | undefined>({
        queryKey: qk.notifications.all(),
      });
      const countersSnapshot = qc.getQueryData<NotificationCountersDto | undefined>(
        qk.notifications.counters(),
      );
      const { flippedByType, flippedTotal } = applyReadToCaches(qc, () => true);
      applyCountersDelta(qc, flippedByType, flippedTotal);
      return { listsSnapshot, countersSnapshot };
    },
    onError: (_err, _vars, ctx) => {
      if (!ctx) return;
      for (const [key, value] of ctx.listsSnapshot) {
        qc.setQueryData(key, value);
      }
      if (ctx.countersSnapshot) {
        qc.setQueryData(qk.notifications.counters(), ctx.countersSnapshot);
      }
    },
    onSettled: () => qc.invalidateQueries({ queryKey: qk.notifications.all() }),
  });
}

/**
 * Bug-13 — shared helper used by ``useLiveNotifications`` to mirror
 * a ``notification.read`` WS event from the backend into the local
 * cache. Exported so the WS hook does not have to duplicate the
 * same splice logic.
 */
export function applyServerNotificationRead(
  qc: ReturnType<typeof useQueryClient>,
  payload: { ids?: number[]; all?: boolean },
): void {
  const idSet = new Set(payload.ids ?? []);
  const predicate = payload.all
    ? () => true
    : (n: NotificationDto) => idSet.has(n.id);
  const { flippedByType, flippedTotal } = applyReadToCaches(qc, predicate);
  applyCountersDelta(qc, flippedByType, flippedTotal);
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
    // Item 8 — re-check ``has_pin`` whenever the user returns to the
    // tab. Without this an admin-side reset stays invisible on the
    // device until either the PIN-JWT TTL expires or the client makes
    // a PIN-gated REST call; the user reported staying on the
    // authenticated tree indefinitely. The companion WS event
    // ``pin.reset`` covers the live-tab case (``useLivePinReset``).
    refetchOnWindowFocus: true,
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

export function useCurrencies(opts: { kind?: "fiat" | "crypto" } = {}) {
  // Item 15 — the user-facing dropdowns pass ``kind="fiat"`` so
  // crypto rows never reach the wire. Cache key includes ``kind`` so
  // a fiat call and a no-filter call don't trample each other.
  return useQuery<CurrencyDto[]>({
    queryKey: opts.kind ? qk.wallet.currenciesByKind(opts.kind) : qk.wallet.currencies(),
    queryFn: () => {
      const sp = opts.kind ? { searchParams: { kind: opts.kind } } : undefined;
      return api.get("api/wallet/currencies", sp).json();
    },
    staleTime: 60 * 60_000,
  });
}

export function useWalletBalances(opts: { kind?: "fiat" | "crypto" } = {}) {
  // Item 15 — same filter logic as ``useCurrencies``; the user-side
  // wallet/profile views pass ``kind="fiat"``.
  return useQuery<WalletBalanceDto[]>({
    queryKey: opts.kind ? qk.wallet.balancesByKind(opts.kind) : qk.wallet.balances(),
    queryFn: () => {
      const sp = opts.kind ? { searchParams: { kind: opts.kind } } : undefined;
      return api.get("api/wallet/balances", sp).json();
    },
    // Always refetch on mount so a user returning to the wallet
    // page after a successful deposit sees the credited balance
    // immediately, even if the WS notification fired while the
    // page was unmounted (e.g. user closed the deposit modal then
    // tabbed away). ``staleTime`` stays at 15s so passive renders
    // don't thrash the API.
    refetchOnMount: "always",
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
  amount: string;
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
  // Audit M-7 — ``amount`` is typed ``string`` here (not ``number``)
  // so the caller passes the user-visible decimal string straight
  // through. The backend's ``WalletWithdrawCreateReq.amount: Decimal``
  // accepts a JSON string and parses it without going through
  // ``float``, preserving every digit. JavaScript's IEEE-754
  // ``Number`` truncates the last 2-3 base-10 digits at the 10^10
  // scale that USDT can hit, so ``parseFloat(amount)`` was leaking
  // user money on big balances.
  // Bug-10 — ``address`` is optional because the CryptoBot Transfer
  // auto-mode payout identifies the recipient by ``users.tg_user_id``
  // and omits the field entirely. Manual mode still requires a real
  // string; the validation lives client-side in ``WalletWithdrawPage``
  // and server-side in ``services_wallet.create_withdrawal``.
  return useMutation({
    mutationFn: (body: {
      currency_code: string;
      amount: string;
      address?: string;
    }) =>
      api.post("api/wallet/withdrawals", { json: body }).json<WalletWithdrawalDto>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.wallet.withdrawals() });
      qc.invalidateQueries({ queryKey: qk.wallet.balances() });
    },
  });
}
