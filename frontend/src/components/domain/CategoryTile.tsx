import {
  Plane,
  Bitcoin,
  Shield,
  Key,
  BadgeCheck,
  Skull,
  Stamp,
  CreditCard,
  Palette,
  FileText,
  Edit,
  Banknote,
  ArrowLeftRight,
  Wallet,
  MoreHorizontal,
  Briefcase,
  type LucideIcon,
} from "lucide-react";
import { Link } from "react-router-dom";
import type { CategoryDto } from "@/api/types";
import { cn } from "@/lib/cn";
import { staggerDelay } from "@/lib/animate";

const ICON_MAP: Record<string, LucideIcon> = {
  plane: Plane,
  bitcoin: Bitcoin,
  shield: Shield,
  key: Key,
  "badge-check": BadgeCheck,
  skull: Skull,
  stamp: Stamp,
  "credit-card": CreditCard,
  palette: Palette,
  "file-text": FileText,
  edit: Edit,
  banknote: Banknote,
  "arrow-left-right": ArrowLeftRight,
  wallet: Wallet,
  "more-horizontal": MoreHorizontal,
};

export function CategoryTile({ category, index = 0 }: { category: CategoryDto; index?: number }) {
  const IconCmp = ICON_MAP[category.icon_key] ?? Briefcase;
  return (
    <div
      className="animate-fade-in-scale"
      style={staggerDelay(index)}
    >
      <Link
        to={`/search/categories/${category.slug}`}
        className={cn(
          "block bg-panel border border-border rounded-card p-3 aspect-square",
          "flex flex-col justify-between active:scale-[.97] transition-transform",
        )}
      >
        <div>
          <div className="font-semibold text-sm leading-tight line-clamp-2">{category.name}</div>
          <div className="mt-1 text-[11px] text-text-muted">Всего: {category.services_count}</div>
        </div>
        <div className="self-end size-10 rounded-full bg-panel-2 grid place-items-center text-accent">
          <IconCmp className="size-5" />
        </div>
      </Link>
    </div>
  );
}
