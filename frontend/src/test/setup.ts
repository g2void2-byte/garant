/**
 * Global Vitest setup.
 *
 * - Registers ``@testing-library/jest-dom`` matchers (``toBeInTheDocument``,
 *   ``toHaveTextContent``, …) on ``expect``.
 * - Auto-cleans React Testing Library mounts after each test so leftover
 *   trees from one test never bleed into the next.
 * - Stubs a couple of browser APIs jsdom doesn't implement
 *   (``IntersectionObserver``, ``matchMedia``, ``ResizeObserver``,
 *   ``scrollTo``) so components that touch them in mount effects don't
 *   throw inside tests.
 */
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});

class MockIntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
  root = null;
  rootMargin = "";
  thresholds = [];
}

class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (typeof window !== "undefined") {
  if (!("IntersectionObserver" in window)) {
    (window as unknown as { IntersectionObserver: typeof MockIntersectionObserver }).IntersectionObserver =
      MockIntersectionObserver;
  }
  if (!("ResizeObserver" in window)) {
    (window as unknown as { ResizeObserver: typeof MockResizeObserver }).ResizeObserver = MockResizeObserver;
  }
  if (!window.matchMedia) {
    window.matchMedia = (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    });
  }
  if (!window.scrollTo) {
    window.scrollTo = (() => {}) as typeof window.scrollTo;
  }
}
