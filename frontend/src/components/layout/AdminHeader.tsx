import type { ReactNode } from "react";
import { Menu } from "lucide-react";
import { Header } from "@/components/layout/Header";
import { useUI } from "@/stores/ui";
import { haptic } from "@/lib/tg";

interface AdminHeaderProps {
  title: string;
  subtitle?: string;
  /**
   * Optional right-aligned content (filter pills, "Add"-button, …).
   * Composed *next to* the burger button so the admin pages can
   * keep their existing right-aligned actions without losing the
   * global menu affordance.
   */
  right?: ReactNode;
}

/**
 * Header variant for /admin/* pages — renders the standard
 * :class:`Header` with a leading Menu button that toggles the
 * global :class:`AdminMenu` drawer via ``useUI.adminMenuOpen``.
 *
 * Mounted on every admin page so the slide-in nav is always one
 * tap away regardless of how the operator arrived.
 */
export function AdminHeader({ title, subtitle, right }: AdminHeaderProps) {
  const toggle = useUI((s) => s.toggleAdminMenu);
  const burger = (
    <button
      type="button"
      onClick={() => {
        haptic("light");
        toggle();
      }}
      aria-label="Открыть меню админки"
      data-testid="admin-menu-toggle"
      className="rounded-button p-2 -m-2 text-text-muted hover:text-text transition"
    >
      <Menu size={22} />
    </button>
  );
  return (
    <Header
      title={title}
      subtitle={subtitle}
      right={
        right ? (
          <div className="flex items-center gap-2">
            {right}
            {burger}
          </div>
        ) : (
          burger
        )
      }
    />
  );
}
