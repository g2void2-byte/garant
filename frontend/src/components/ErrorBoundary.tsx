import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RotateCw } from "lucide-react";

/**
 * App-wide error boundary (V12-I5).
 *
 * Catches uncaught render / lifecycle errors thrown anywhere in the
 * subtree and replaces the broken UI with a self-contained overlay so
 * the user sees a recoverable surface instead of a blank white screen.
 *
 * The fallback intentionally depends on **nothing** from the React
 * tree beneath it (no context, no react-query, no router, no toast) —
 * if the broken render is inside one of those providers the fallback
 * must still mount. Tailwind utility classes resolve to static CSS,
 * so they remain available even when every provider above us has
 * unmounted.
 *
 * Two recovery affordances:
 *   * "Try again" clears ``state.error`` and re-renders ``children``.
 *     This is sufficient when the error was transient (e.g. a query
 *     payload mismatched on first paint and a refetch will fix it).
 *   * "Reload" hard-reloads the page so the entire JS bundle restarts
 *     from a clean slate.
 *
 * TanStack Query errors are not auto-thrown into render today
 * (``queryClient`` keeps the default ``throwOnError: false``); 4xx/5xx
 * responses are surfaced per-call via ``useToast``. This boundary is
 * the safety net for *unexpected* exceptions — null dereferences,
 * malformed cache shapes, lazy-chunk load failures — that would
 * otherwise propagate to React's "uncaught error" path and white-screen
 * the Mini App.
 */
interface ErrorBoundaryProps {
  children: ReactNode;
  /** Override the default overlay. Useful for unit tests. */
  fallback?: (error: Error, reset: () => void) => ReactNode;
  /** Side-channel hook for telemetry. Called once per caught error. */
  onError?: (error: Error, info: ErrorInfo) => void;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Mirror the stack into ``console.error`` so the DevTools error
    // path is still populated even though React's default "uncaught"
    // overlay has been suppressed by this boundary.
    if (typeof console !== "undefined") {
      console.error("[ErrorBoundary]", error, info.componentStack);
    }
    this.props.onError?.(error, info);

    // Audit v3 L-9 — report the error to the backend so it surfaces
    // in server-side logs / Sentry. Fire-and-forget; never block the
    // fallback UI on a failed report.
    try {
      const body = JSON.stringify({
        message: error.message?.slice(0, 2000) ?? "unknown",
        stack: error.stack?.slice(0, 8000) ?? "",
        component_stack: (info.componentStack ?? "").slice(0, 4000),
        url: typeof window !== "undefined" ? window.location.href : "",
        user_agent: typeof navigator !== "undefined" ? navigator.userAgent : "",
      });
      fetch("/api/errors/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      }).catch(() => {});
    } catch {
      /* swallow — the fallback UI must always render */
    }
  }

  private readonly handleReset = (): void => {
    this.setState({ error: null });
  };

  private readonly handleReload = (): void => {
    if (typeof window !== "undefined") {
      window.location.reload();
    }
  };

  render(): ReactNode {
    const { error } = this.state;
    if (error === null) {
      return this.props.children;
    }

    if (this.props.fallback) {
      return this.props.fallback(error, this.handleReset);
    }

    return (
      <div
        role="alert"
        aria-live="assertive"
        className="fixed inset-0 z-[100] grid place-items-center bg-bg/95 p-4 animate-fadein"
        data-testid="error-boundary-overlay"
      >
        <div className="w-full max-w-md rounded-card border border-border bg-panel p-5 shadow-pop">
          <div className="flex items-start gap-3">
            <div className="size-10 grid place-items-center rounded-full bg-danger/10 text-danger shrink-0">
              <AlertTriangle className="size-5" />
            </div>
            <div className="min-w-0">
              <div className="font-semibold">Что-то пошло не так</div>
              <div className="text-sm text-text-muted">
                Произошла непредвиденная ошибка. Попробуйте ещё раз или перезагрузите страницу.
              </div>
            </div>
          </div>
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={this.handleReset}
              className="flex-1 h-11 rounded-button border border-border bg-secondary text-text text-base font-medium hover:opacity-90 active:opacity-80 transition-opacity"
            >
              Попробовать ещё раз
            </button>
            <button
              type="button"
              onClick={this.handleReload}
              className="flex-1 h-11 rounded-button bg-accent text-black text-base font-medium flex items-center justify-center gap-2 hover:brightness-95 active:brightness-90 transition"
            >
              <RotateCw className="size-4" />
              Перезагрузить
            </button>
          </div>
        </div>
      </div>
    );
  }
}
