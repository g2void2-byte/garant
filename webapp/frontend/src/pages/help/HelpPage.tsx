import { useState } from "react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { ToggleTabs } from "@/components/ui/ToggleTabs";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { SupportPersonRow } from "@/components/domain/SupportPersonRow";
import { useAdmins, useArbiters } from "@/api/hooks";

export default function HelpPage() {
  const [tab, setTab] = useState<"admins" | "arbiters">("admins");
  const { data: admins, isLoading: loadingAdmins } = useAdmins();
  const { data: arbiters, isLoading: loadingArbiters } = useArbiters();

  const list = tab === "admins" ? admins : arbiters;
  const loading = tab === "admins" ? loadingAdmins : loadingArbiters;

  return (
    <Page>
      <Header title="Помощь" subtitle="Свяжитесь с командой" />
      <div className="px-4 space-y-3">
        <ToggleTabs
          value={tab}
          options={[
            { value: "admins", label: "Администрация", count: admins?.length ?? 0 },
            { value: "arbiters", label: "Арбитры", count: arbiters?.length ?? 0 },
          ]}
          onChange={setTab}
          layoutId="help-tabs"
        />

        {loading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-16" />
            ))}
          </div>
        ) : !list || list.length === 0 ? (
          <EmptyState title="Никого нет в этой группе" />
        ) : (
          <ul className="space-y-2">
            {list.map((p, i) => (
              <li key={p.id}>
                <SupportPersonRow person={p} index={i} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </Page>
  );
}
