import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { DealRow } from "./DealRow";
import type { DealDto } from "@/api/types";

const baseDeal: DealDto = {
  id: 17,
  buyer: "alice",
  seller: "bob",
  description: "Logo design package",
  status: "in_progress",
  confirm_buyer: false,
  confirm_seller: false,
  role: "buyer",
  created_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
  currency_code: "USDT",
  amount: 100,
  commission_amount: 5,
  commission_paid: true,
  topup_deposit_id: null,
  topup_invoice: null,
  in_progress_at: null,
  completed_at: null,
  cancellation_initiator: null,
  cancellation_reason: null,
  cancellation_requested_at: null,
  arbitration_initiator: null,
  arbitration_reason: null,
  arbitration_resolved_by: null,
  arbitration_resolution: null,
  arbitration_resolved_at: null,
};

function renderRow(deal: Partial<DealDto> = {}) {
  return render(
    <MemoryRouter>
      <DealRow deal={{ ...baseDeal, ...deal }} />
    </MemoryRouter>,
  );
}

function LocationProbe() {
  const loc = useLocation();
  return <span data-testid="path">{loc.pathname}</span>;
}

function renderRowWithLocation(deal: Partial<DealDto> = {}) {
  return render(
    <MemoryRouter>
      <DealRow deal={{ ...baseDeal, ...deal }} />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe("<DealRow />", () => {
  it("renders the deal description and id", () => {
    renderRow();
    expect(screen.getByText("Logo design package")).toBeInTheDocument();
    expect(screen.getByText("#17")).toBeInTheDocument();
  });

  it("opens the deal detail page from the row link", async () => {
    const user = userEvent.setup();
    renderRowWithLocation();
    const detailLink = screen
      .getAllByRole("link")
      .find((link) => link.getAttribute("href") === null);

    expect(detailLink).toBeDefined();
    await user.click(detailLink!);
    expect(screen.getByTestId("path").textContent).toBe("/deals/17");
  });

  it("uses canonical deal routes for decimal-string runtime ids", async () => {
    const user = userEvent.setup();
    renderRowWithLocation({ id: "17" as unknown as number });

    const detailLink = screen
      .getAllByRole("link")
      .find((link) => link.getAttribute("href") === null);

    expect(screen.getByText("#17")).toBeInTheDocument();
    expect(detailLink).toBeDefined();
    await user.click(detailLink!);
    expect(screen.getByTestId("path").textContent).toBe("/deals/17");
  });

  it("does not build deal routes from malformed runtime ids", () => {
    renderRowWithLocation({ id: "0x11" as unknown as number });

    expect(screen.getByText("#\u2014")).toBeInTheDocument();
    expect(screen.queryByText(/0x11/)).not.toBeInTheDocument();
    const rowLinks = screen
      .getAllByRole("link")
      .filter((link) => link.getAttribute("href") === null);
    expect(rowLinks).toHaveLength(0);
  });

  it("renders the in-progress status label", () => {
    renderRow();
    expect(screen.getByText("В работе")).toBeInTheDocument();
  });

  it("renders the arbitration status label", () => {
    renderRow({ status: "arbitration" });
    expect(screen.getByText("Арбитраж")).toBeInTheDocument();
  });

  it("renders unknown runtime statuses as a neutral label", () => {
    renderRow({ status: "provider_reconciled" });

    expect(screen.getByText("Статус неизвестен")).toBeInTheDocument();
    expect(screen.queryByText("provider_reconciled")).not.toBeInTheDocument();
  });

  it("shows the seller from the buyer perspective", () => {
    renderRow({ role: "buyer", seller: "bob" });
    expect(screen.getByText("Продавец: @bob")).toBeInTheDocument();
    expect(screen.getByText("Покупка")).toBeInTheDocument();
  });

  it("shows the buyer from the seller perspective", () => {
    renderRow({ role: "seller", buyer: "alice" });
    expect(screen.getByText("Покупатель: @alice")).toBeInTheDocument();
    expect(screen.getByText("Продажа")).toBeInTheDocument();
  });

  it("renders unknown runtime roles as neutral deal rows", () => {
    renderRow({ role: "auditor", buyer: "alice", seller: "bob" });

    expect(screen.getByText("Контрагент: профиль недоступен")).toBeInTheDocument();
    expect(screen.getByText("Сделка")).toBeInTheDocument();
    expect(screen.queryByText("Покупка")).not.toBeInTheDocument();
    expect(screen.queryByText("Продажа")).not.toBeInTheDocument();
    const profileLink = screen
      .getAllByRole("link")
      .find((link) => link.getAttribute("href")?.startsWith("/users/"));
    expect(profileLink).toBeUndefined();
  });

  it("renders the amount with currency code", () => {
    renderRow({ amount: 250, currency_code: "USDT" });
    expect(screen.getByText("250")).toBeInTheDocument();
    expect(screen.getAllByText("USDT").length).toBeGreaterThan(0);
  });

  it("does not render malformed runtime currency codes", () => {
    renderRow({ amount: 250, currency_code: "../USD" });

    expect(screen.getByText("250")).toBeInTheDocument();
    expect(screen.queryByText(/\.\.\/USD/)).not.toBeInTheDocument();
  });

  it("renders malformed deal amounts as neutral instead of zero", () => {
    renderRow({ amount: "1e2" as unknown as number, currency_code: "USDT" });

    expect(screen.getByText("\u2014")).toBeInTheDocument();
    expect(screen.getAllByText("USDT").length).toBeGreaterThan(0);
    expect(screen.queryByText("0")).not.toBeInTheDocument();
    expect(screen.queryByText(/1e2/)).not.toBeInTheDocument();
  });

  it("links the 'Профиль' button to the counterparty profile", () => {
    renderRow({ role: "buyer", seller: "bob" });
    const links = screen.getAllByRole("link");
    const profileLink = links.find((l) => l.getAttribute("href") === "/users/bob");
    expect(profileLink).toBeDefined();
    expect(profileLink).toHaveTextContent("Профиль");
  });

  it("does not let the profile link click bubble into deal navigation", async () => {
    const user = userEvent.setup();
    renderRowWithLocation({ role: "buyer", seller: "bob" });
    const profileLink = screen
      .getAllByRole("link")
      .find((link) => link.getAttribute("href") === "/users/bob");

    expect(profileLink).toBeDefined();
    await user.click(profileLink!);
    expect(screen.getByTestId("path").textContent).toBe("/users/bob");
  });

  it("does not render @null or a profile link when the counterparty username is missing", () => {
    renderRow({ role: "buyer", seller: null });
    expect(screen.getByText("Продавец: профиль недоступен")).toBeInTheDocument();
    expect(screen.queryByText("@null")).not.toBeInTheDocument();
    expect(screen.queryByText("Профиль")).not.toBeInTheDocument();
  });

  it("does not render profile links for unsafe counterparty usernames", () => {
    renderRow({ role: "buyer", seller: "../admin" });
    expect(screen.queryByText("@../admin")).not.toBeInTheDocument();
    const profileLink = screen
      .getAllByRole("link")
      .find((link) => link.getAttribute("href")?.startsWith("/users/"));
    expect(profileLink).toBeUndefined();
  });

  it("renders the counterparty avatar with the seller's photo for a buyer-side row", () => {
    renderRow({
      role: "buyer",
      seller: "bob",
      seller_photo_url: "https://example.com/bob.jpg",
    });
    const img = screen.getByAltText("bob") as HTMLImageElement;
    expect(img).toBeInTheDocument();
    expect(img.src).toBe("https://example.com/bob.jpg");
  });
});
