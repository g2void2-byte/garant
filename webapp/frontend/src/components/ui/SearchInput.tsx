import { Search } from "lucide-react";
import type { InputHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

interface SearchInputProps extends InputHTMLAttributes<HTMLInputElement> {
  containerClassName?: string;
}

export function SearchInput({ containerClassName, className, ...rest }: SearchInputProps) {
  return (
    <div className={cn("relative flex items-center", containerClassName)}>
      <Search className="absolute left-3 size-4 text-text-muted" />
      <input
        type="text"
        className={cn(
          "h-12 w-full pl-10 pr-3 rounded-2xl bg-panel-2 border border-border text-text",
          "placeholder:text-text-muted focus:outline-none focus:border-accent",
          "transition-colors duration-150",
          className,
        )}
        {...rest}
      />
    </div>
  );
}
