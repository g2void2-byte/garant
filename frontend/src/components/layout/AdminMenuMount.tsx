import { useLocation } from "react-router-dom";
import { AdminMenu } from "@/components/layout/AdminMenu";
import { useUI } from "@/stores/ui";

/**
 * Global mount point for the admin slide-in menu.
 *
 * The drawer is mounted only on /admin/* routes so the rest of the
 * app doesn't pay the (small) DOM cost. Visibility is driven by
 * ``useUI.adminMenuOpen`` — toggled by :class:`AdminHeader`'s menu
 * button on each admin page.
 */
export function AdminMenuMount() {
  const { pathname } = useLocation();
  const open = useUI((s) => s.adminMenuOpen);
  const setOpen = useUI((s) => s.setAdminMenuOpen);

  if (!pathname.startsWith("/admin")) return null;
  return <AdminMenu open={open} onClose={() => setOpen(false)} />;
}
