import { lazy, type ComponentType } from "react";

// ``React.lazy`` itself widens to ``ComponentType<any>`` (see the
// upstream typings) so callers can keep their original prop types
// without contorting them through ``ComponentType<unknown>``. Match
// that shape here so ``lazyWithRetry`` is a drop-in replacement.
type AnyComponent = ComponentType<any>;

/**
 * Resilient wrapper around ``React.lazy`` for code-split route chunks.
 *
 * In Vite-served dev mode (and in production after a re-deploy), the
 * dynamic ``import("./SomePage.tsx")`` request can fail with
 * ``Failed to fetch dynamically imported module: …`` whenever:
 *
 *   * the dev server was restarted while the tab was open and the
 *     module graph hash on disk no longer matches the URL the
 *     browser cached;
 *   * a transient network glitch dropped the chunk request before the
 *     route component mounted;
 *   * a fresh production build replaced the hashed chunk filenames the
 *     long-lived tab still remembers.
 *
 * Letting the rejected promise bubble up trips the top-level
 * ``ErrorBoundary`` and white-screens the user mid-navigation — the
 * exact symptom reported on ``/deals/<id>`` ("TypeError: Failed to
 * fetch dynamically imported module: …/DealDetailPage.tsx"). This
 * helper turns that failure into a one-time hard reload: on the first
 * failure we wipe the stale chunk reference by forcing a full page
 * reload, which fetches the fresh ``index.html`` (and with it the
 * up-to-date chunk URLs) so the next render resolves cleanly. The
 * ``sessionStorage`` guard prevents a reload loop if the chunk is
 * genuinely broken — after one attempt the rejection propagates and
 * the ``ErrorBoundary`` overlay takes over.
 */
const RELOAD_KEY_PREFIX = "garant.chunk_reload:";

export function lazyWithRetry<T extends AnyComponent>(
  factory: () => Promise<{ default: T }>,
  cacheKey?: string,
) {
  return lazy(async () => {
    try {
      return await factory();
    } catch (err) {
      const key = `${RELOAD_KEY_PREFIX}${cacheKey ?? factory.toString().slice(0, 60)}`;
      if (typeof window !== "undefined" && typeof sessionStorage !== "undefined") {
        const reloaded = sessionStorage.getItem(key);
        if (!reloaded) {
          sessionStorage.setItem(key, "1");
          // Force-fetch the latest ``index.html`` so the browser
          // re-discovers the current chunk URLs. ``true`` was the
          // legacy ``forcedReload`` flag — it's still honoured by
          // every browser engine even though the typings dropped it.
          window.location.reload();
          // Return a never-resolving promise so React keeps the
          // ``Suspense`` fallback up while the reload happens.
          return new Promise<{ default: T }>(() => {});
        }
        // Clear so a subsequent successful load doesn't keep the
        // "we already tried" flag forever in this tab.
        sessionStorage.removeItem(key);
      }
      throw err;
    }
  });
}
