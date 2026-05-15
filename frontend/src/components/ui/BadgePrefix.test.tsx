import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { BadgePrefix } from "./BadgePrefix";

describe("<BadgePrefix />", () => {
  it("renders nothing when prefix is null", () => {
    const { container } = render(<BadgePrefix prefix={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders the admin label", () => {
    render(<BadgePrefix prefix="admin" />);
    expect(screen.getByText("Админ")).toBeInTheDocument();
  });

  it("renders the arbiter label", () => {
    render(<BadgePrefix prefix="arbiter" />);
    expect(screen.getByText("Арбитр")).toBeInTheDocument();
  });

  it("renders the VIP label", () => {
    render(<BadgePrefix prefix="vip" />);
    expect(screen.getByText("VIP")).toBeInTheDocument();
  });
});
