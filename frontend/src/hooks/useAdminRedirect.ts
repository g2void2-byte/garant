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
   * ``true`` while ``me`` is loading; ``true`` if the visitor is
   * allowed; ``false`` if a redirect was scheduled. Callers should
   * ``return null`` (or render nothing) when this is ``false`` so the
   * admin scaffolding doesn't flash before the navigation runs.
   *
   * ``null`` is never returned — the loading state is collapsed into
   * ``true`` so most pages can keep their existing skeleton loaders.
   */
  shouldRender: boolean;
}

export function useAdminRedirect(opts: UseAdminRedirectOptions = {}): AdminRedirectResult {
  const { allowArbiter = false, redirectTo = "/search" } = opts;
  const navigate = useNavigate();
  const { data: me } = useMe();

  const allowed: boolean = me ? Boolean(me.is_admin || (allowArbiter && me.is_arbiter)) : true;

  useEffect(() => {
    if (me && !me.is_admin && !(allowArbiter && me.is_arbiter)) {
      navigate(redirectTo, { replace: true });
    }
  }, [me, allowArbiter, redirectTo, navigate]);

  return { shouldRender: allowed };
}
