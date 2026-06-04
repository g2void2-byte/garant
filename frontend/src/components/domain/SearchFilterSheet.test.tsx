import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SearchFilterSheet, type SearchFilters } from "./SearchFilterSheet";

vi.mock("@/lib/tg", () => ({
  haptic: () => {},
  useTelegramViewport: () => null,
}));

function renderSheet(onApply = vi.fn<(next: SearchFilters) => void>()) {
  render(
    <SearchFilterSheet
      open
      value={{}}
      onApply={onApply}
      onClose={vi.fn()}
    />,
  );
  return onApply;
}

function dateInputs(): HTMLInputElement[] {
  return Array.from(document.querySelectorAll<HTMLInputElement>('input[type="date"]'));
}

describe("<SearchFilterSheet />", () => {
  it("blocks reversed registration date ranges before applying", async () => {
    const user = userEvent.setup();
    const onApply = renderSheet();
    const [from, to] = dateInputs();

    fireEvent.change(from, { target: { value: "2026-06-10" } });
    fireEvent.change(to, { target: { value: "2026-06-01" } });

    const apply = screen.getByText("\u041f\u0440\u0438\u043c\u0435\u043d\u0438\u0442\u044c \u0444\u0438\u043b\u044c\u0442\u0440\u044b").closest("button");
    expect(apply).toBeDisabled();
    await user.click(apply!);

    expect(onApply).not.toHaveBeenCalled();
  });

  it("applies a valid registration date range", async () => {
    const user = userEvent.setup();
    const onApply = renderSheet();
    const [from, to] = dateInputs();

    fireEvent.change(from, { target: { value: "2026-06-01" } });
    fireEvent.change(to, { target: { value: "2026-06-10" } });
    await user.click(screen.getByText("\u041f\u0440\u0438\u043c\u0435\u043d\u0438\u0442\u044c \u0444\u0438\u043b\u044c\u0442\u0440\u044b"));

    expect(onApply).toHaveBeenCalledWith({
      reg_from: "2026-06-01",
      reg_to: "2026-06-10",
    });
  });
});
