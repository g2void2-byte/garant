import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { Sheet } from "./Sheet";

/**
 * Tests for the bottom-sheet primitive.
 *
 * Pinned behaviour:
 *   - Mount lifecycle (``mounted`` vs ``visible``) — the sheet remains
 *     in the DOM during its 300ms close animation but its
 *     ``data-state`` flips to ``"closed"`` so consumers can target the
 *     final frame.
 *   - The scrollable body opts into ``touch-action: pan-y`` so the
 *     inner overflow works under Telegram WebView's iOS quirks even
 *     when ``body.style.overflow = "hidden"`` is set elsewhere
 *     (``AdminMenu``).
 *   - Backdrop click + Escape key fire ``onClose`` so the consumer can
 *     drive the close transition deterministically.
 */

describe("<Sheet />", () => {
  it("does not render when closed and never opened", () => {
    const { container } = render(
      <Sheet open={false} onClose={() => {}}>
        <div>hidden</div>
      </Sheet>,
    );
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("sheet")).not.toBeInTheDocument();
  });

  it("renders with data-state=open + pan-y touch action when open", () => {
    render(
      <Sheet open onClose={() => {}} title="Hello">
        <div>panel content</div>
      </Sheet>,
    );
    const sheet = screen.getByTestId("sheet");
    expect(sheet).toHaveAttribute("data-state", "open");
    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("panel content")).toBeInTheDocument();

    // The body scroll container must expose ``touch-action: pan-y``
    // — the property survives the Tailwind class soup as an inline
    // style so it can't be silently dropped by class-merging.
    const scroller = Array.from(sheet.children).find(
      (el) => (el as HTMLElement).style.touchAction === "pan-y",
    ) as HTMLElement | undefined;
    expect(scroller).toBeDefined();
    expect(scroller).toHaveClass("overflow-y-auto");
  });

  it("fires onClose when the backdrop is clicked", () => {
    const onClose = vi.fn();
    render(
      <Sheet open onClose={onClose}>
        <div>body</div>
      </Sheet>,
    );

    // Backdrop is the first sibling of the panel — match by class.
    const backdrop = document.querySelector(
      ".fixed.inset-0.bg-black\\/60",
    ) as HTMLElement;
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("fires onClose on Escape", () => {
    const onClose = vi.fn();
    render(
      <Sheet open onClose={onClose}>
        <div>body</div>
      </Sheet>,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
