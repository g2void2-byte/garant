import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { DealMessageDto, MediaDto } from "@/api/types";

const mockState = vi.hoisted(() => ({
  me: { id: 100 },
  messages: [] as any[],
  isLoading: false,
  sendMessage: {
    mutateAsync: vi.fn(),
    isPending: false,
  },
  loadOlder: {
    mutateAsync: vi.fn(),
    isPending: false,
  },
  uploadMedia: {
    mutateAsync: vi.fn(),
    isPending: false,
  },
}));

vi.mock("@/api/hooks", () => ({
  DEAL_MESSAGE_PAGE_SIZE: 50,
  useMe: () => ({ data: mockState.me }),
  useDealMessages: () => ({
    data: mockState.messages,
    isLoading: mockState.isLoading,
  }),
  useSendDealMessage: () => mockState.sendMessage,
  useLoadOlderDealMessages: () => mockState.loadOlder,
  useUploadMedia: () => mockState.uploadMedia,
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

const hapticSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/tg", () => ({
  haptic: hapticSpy,
}));

import { DealChatPanel } from "./DealChatPanel";

function makeMedia(overrides: Partial<MediaDto> = {}): MediaDto {
  return {
    id: 10,
    kind: "deal",
    url: "/media/deal/proof.png?exp=1&sig=abc",
    name: "proof.png",
    size: 123,
    content_type: "image/png",
    created_at: null,
    ...overrides,
  };
}

function makeMessage(
  overrides: Partial<DealMessageDto> = {},
): DealMessageDto {
  return {
    id: 1,
    deal_id: 42,
    sender_id: 200,
    sender_username: "alice",
    text: "hello",
    attachments: [],
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  mockState.me = { id: 100 };
  mockState.messages = [];
  mockState.isLoading = false;
  mockState.sendMessage = { mutateAsync: vi.fn(), isPending: false };
  mockState.loadOlder = { mutateAsync: vi.fn(), isPending: false };
  mockState.uploadMedia = { mutateAsync: vi.fn(), isPending: false };
  toastSpy.mockClear();
  hapticSpy.mockClear();
});

describe("<DealChatPanel />", () => {
  it("renders safe media URLs as attachment links and image previews", () => {
    const media = makeMedia();
    mockState.messages = [makeMessage({ attachments: [media] })];

    render(<DealChatPanel dealId={42} />);

    const link = screen.getByRole("link", { name: "proof.png" });
    expect(link).toHaveAttribute(
      "href",
      "/media/deal/proof.png?exp=1&sig=abc",
    );
    expect(screen.getByRole("img", { name: "proof.png" })).toHaveAttribute(
      "src",
      "/media/deal/proof.png?exp=1&sig=abc",
    );
  });

  it("renders malformed media URLs as inert broken-preview placeholders", () => {
    const media = makeMedia({ url: "javascript:alert(1)" });
    mockState.messages = [makeMessage({ attachments: [media] })];

    render(<DealChatPanel dealId={42} />);

    expect(screen.queryByRole("link", { name: /proof\.png/i })).not.toBeInTheDocument();
    expect(screen.queryByAltText("proof.png")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: /proof\.png/i })).toBeInTheDocument();
  });

  it("normalizes string cursor ids before loading older messages", async () => {
    mockState.messages = Array.from({ length: 50 }, (_, index) =>
      makeMessage({
        id: (index === 0 ? "100" : 101 + index) as unknown as number,
        text: `message ${index}`,
      }),
    );
    mockState.loadOlder.mutateAsync.mockResolvedValue([]);
    const user = userEvent.setup();

    render(<DealChatPanel dealId={42} />);
    await user.click(screen.getAllByRole("button")[0]);

    await waitFor(() =>
      expect(mockState.loadOlder.mutateAsync).toHaveBeenCalledWith({ beforeId: 100 }),
    );
  });

  it("does not load older messages with malformed runtime cursor ids", async () => {
    mockState.messages = Array.from({ length: 50 }, (_, index) =>
      makeMessage({
        id: (index === 0 ? "0x64" : 101 + index) as unknown as number,
        text: `message ${index}`,
      }),
    );
    const user = userEvent.setup();

    render(<DealChatPanel dealId={42} />);
    await user.click(screen.getAllByRole("button")[0]);

    expect(mockState.loadOlder.mutateAsync).not.toHaveBeenCalled();
    expect(toastSpy).toHaveBeenCalledWith({
      kind: "error",
      title: "\u041d\u0435\u0432\u0435\u0440\u043d\u044b\u0439 ID \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f",
    });
  });
});
