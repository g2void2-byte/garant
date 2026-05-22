/**
 * Centralised "kick non-admins off this page" hook.
 *
 * The previous pattern across the ``frontend/src/pages/admin/*`` files
 * was:
 *
 *   if (me && !me.is_admin) {
 *     navigate("/search", { replace: true });
 *     return null;
 *   }
 *
 * Calling ``navigate()`` synchronously during render triggers a React
 * warning ("Cannot update a component while rendering a different
 * component"). Wrapping the redirect in ``useEffect`` is the canonical
 * fix, and pulling the pattern into one hook removes ~17 copies of the
 * same boilerplate.
 *
 * Usage:
 *
 *   const guard = useAdminRedirect();
 *   if (guard.shouldRender === false) return null;
 *
 * ``shouldRender === null`` means ``me`` is still loading — callers can
 * choose to render a placeholder, but most pages already show their own
 * skeleton based on their data hooks, so falling through is fine.
 *
 * Pass ``{ allowArbiter: true }`` for pages that arbiters may also
 * access (currently arbitration + deal-detail).
 */

import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { useMe } from "@/api/hooks";

interface UseAdminRedirectOptions {
  /** Allow ``me.is_arbiter`` in addition to ``me.is_admin``. */
  allowArbiter?: boolean;
  /** Where to send unauthorised visitors. Defaults to ``/search``. */
  redirectTo?: string;
}

interface AdminRedirectResult {
  /**
   * ``false`` while ``me`` is still loading (audit M-6: collapsing the
   * loading state into ``true`` flashed the entire admin scaffolding
   * to non-admins on slow networks). ``true`` once ``me`` resolves
   * and the visitor passes the role check; ``false`` once the
   * visitor fails the check (a redirect is scheduled in the same
   * effect). Callers should ``return null`` (or render nothing) when
   * this is ``false`` so the admin chrome doesn't render before
   * ``me`` arrives or before the navigation runs.
   */
  shouldRender: boolean;
}

export function useAdminRedirect(opts: UseAdminRedirectOptions = {}): AdminRedirectResult {
  const { allowArbiter = false, redirectTo = "/search" } = opts;
  const navigate = useNavigate();
  const { data: me } = useMe();

  // Audit M-6 — treat "``me`` not loaded yet" as "do not render". The
  // backend already blocks the admin REST surface for non-admins
  // (``require_admin`` → 403) so no protected data leaks during the
  // flash, but the admin **navigation map** (page titles, side panel
  // entries, table column headers) used to render for ~1 RTT to every
  // signed-in user on the route while ``useMe()`` was in-flight. The
  // ``me ? (...) : false`` default closes that window cleanly.
  const allowed: boolean = me ? Boolean(me.is_admin || (allowArbiter && me.is_arbiter)) : false;

  useEffect(() => {
    if (me && !me.is_admin && !(allowArbiter && me.is_arbiter)) {
      navigate(redirectTo, { replace: true });
    }
  }, [me, allowArbiter, redirectTo, navigate]);

  return { shouldRender: allowed };
}
