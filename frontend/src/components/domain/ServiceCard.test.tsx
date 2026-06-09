import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ServiceCard } from "./ServiceCard";
import type { ServiceDto } from "@/api/types";

const baseService: ServiceDto = {
  id: 42,
  owner_username: "alice",
  title: "Logo design",
  description: "Vector logo + brand book",
  price: 250,
  currency: "USDT",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  category: {
    id: 1,
    slug: "design",
    name: "Design",
    icon_key: "design",
    services_count: 10,
  },
};

function renderCard(svc: Partial<ServiceDto> = {}) {
  return render(
    <MemoryRouter>
      <ServiceCard service={{ ...baseService, ...svc }} />
    </MemoryRouter>,
  );
}

describe("<ServiceCard />", () => {
  it("renders title, description, owner and price", () => {
    renderCard();
    expect(screen.getByText("Logo design")).toBeInTheDocument();
    expect(screen.getByText("Vector logo + brand book")).toBeInTheDocument();
    expect(screen.getByText("@alice")).toBeInTheDocument();
    expect(screen.getByText("$250")).toBeInTheDocument();
  });

  it("renders string price payloads without accepting exponent notation", () => {
    renderCard({ price: "1500" as unknown as number });
    expect(screen.getByText("$1.5k+")).toBeInTheDocument();
    renderCard({ price: "1e3" as unknown as number });
    expect(screen.getByText("\u2014")).toBeInTheDocument();
    expect(screen.queryByText("$0")).not.toBeInTheDocument();
  });

  it("renders a fallback when the service owner username is missing", () => {
    renderCard({ owner_username: null });
    expect(screen.getByText("Владелец недоступен")).toBeInTheDocument();
    expect(screen.queryByText("@null")).not.toBeInTheDocument();
  });

  it("renders a fallback when the service owner username is unsafe", () => {
    renderCard({ owner_username: "../admin" });
    expect(screen.getByText(/\u0412\u043b\u0430\u0434\u0435\u043b\u0435\u0446 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d/)).toBeInTheDocument();
    expect(screen.queryByText("@../admin")).not.toBeInTheDocument();
  });

  it("renders the category label", () => {
    renderCard();
    expect(screen.getByText("Design")).toBeInTheDocument();
  });

  it("links to the service detail page", () => {
    renderCard();
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/services/42");
  });

  it("does not build detail links from malformed runtime ids", () => {
    renderCard({ id: "0x2a" as unknown as number });
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("aria-disabled", "true");
    expect(link.getAttribute("href")).not.toContain("/services/0x2a");
  });

  it("renders a status badge when the service is paused", () => {
    renderCard({ status: "paused" });
    expect(screen.getByText("На паузе")).toBeInTheDocument();
  });

  it("renders the banned badge for blocked services", () => {
    renderCard({ status: "banned" });
    expect(screen.getByText("Заблокировано")).toBeInTheDocument();
  });

  it("renders unknown runtime statuses as a neutral badge", () => {
    renderCard({ status: "provider_reconciled" });
    expect(screen.getByText("Статус неизвестен")).toBeInTheDocument();
    expect(screen.queryByText("provider_reconciled")).not.toBeInTheDocument();
  });
});
