import { Construction } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { EmptyState } from "@/components/ui/EmptyState";

interface StubPageProps {
  title: string;
  description?: string;
}

export function StubPage({ title, description }: StubPageProps) {
  return (
    <Page showBack>
      <Header title={title} />
      <div className="px-4">
        <EmptyState
          icon={<Construction className="size-6" />}
          title="Раздел в разработке"
          description={description ?? "Скоро здесь появится функционал."}
        />
      </div>
    </Page>
  );
}
