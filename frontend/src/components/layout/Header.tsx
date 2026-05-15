import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface HeaderProps {
  title: string;
  subtitle?: string;
  right?: ReactNode;
  centered?: boolean;
}

export function Header({ title, subtitle, right, centered }: HeaderProps) {
  return (
    <header className={cn("safe-top px-4 pt-4 pb-3 flex items-start gap-3", centered && "justify-center text-center")}>
      <div className="flex-1 animate-fade-in-down">
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-text-muted">{subtitle}</p>}
      </div>
      {right}
    </header>
  );
}
