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

  it("renders a fallback when the service owner username is missing", () => {
    renderCard({ owner_username: null });
    expect(screen.getByText("Владелец недоступен")).toBeInTheDocument();
    expect(screen.queryByText("@null")).not.toBeInTheDocument();
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

  it("renders a status badge when the service is paused", () => {
    renderCard({ status: "paused" });
    expect(screen.getByText("На паузе")).toBeInTheDocument();
  });

  it("renders the banned badge for blocked services", () => {
    renderCard({ status: "banned" });
    expect(screen.getByText("Заблокировано")).toBeInTheDocument();
  });
});
