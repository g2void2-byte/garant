import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { DealRow } from "./DealRow";
import type { DealDto } from "@/api/types";

const baseDeal: DealDto = {
  id: 17,
  buyer: "alice",
  seller: "bob",
  description: "Logo design package",
  pay_comission: "buyer",
  status: "in_progress",
  confirm_buyer: false,
  confirm_seller: false,
  role: "buyer",
  created_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
  currency_code: "USDT",
  amount: 100,
  commission_amount: 5,
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

describe("<DealRow />", () => {
  it("renders the deal description and id", () => {
    renderRow();
    expect(screen.getByText("Logo design package")).toBeInTheDocument();
    expect(screen.getByText("#17")).toBeInTheDocument();
  });

  it("links to the deal detail page", () => {
    renderRow();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/deals/17");
  });

  it("renders the in-progress status label", () => {
    renderRow();
    expect(screen.getByText("В работе")).toBeInTheDocument();
  });

  it("renders the arbitration status label", () => {
    renderRow({ status: "arbitration" });
    expect(screen.getByText("Арбитраж")).toBeInTheDocument();
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

  it("renders the amount with currency code", () => {
    renderRow({ amount: 250, currency_code: "USDT" });
    expect(screen.getByText("250")).toBeInTheDocument();
    expect(screen.getAllByText("USDT").length).toBeGreaterThan(0);
  });
});
