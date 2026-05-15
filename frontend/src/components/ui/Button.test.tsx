import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Button } from "./Button";

describe("<Button />", () => {
  it("renders its children", () => {
    render(<Button>Send</Button>);
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("fires onClick when not disabled", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Click</Button>);
    await user.click(screen.getByRole("button", { name: "Click" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("does not fire onClick when disabled", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Click
      </Button>,
    );
    await user.click(screen.getByRole("button", { name: "Click" }));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("applies the primary variant class by default", () => {
    render(<Button>Primary</Button>);
    const btn = screen.getByRole("button", { name: "Primary" });
    expect(btn.className).toMatch(/bg-accent/);
  });

  it("applies the danger variant class when requested", () => {
    render(<Button variant="danger">Danger</Button>);
    const btn = screen.getByRole("button", { name: "Danger" });
    expect(btn.className).toMatch(/bg-danger/);
  });
});
