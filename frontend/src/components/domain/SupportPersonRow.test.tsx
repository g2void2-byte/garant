import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SupportPersonRow } from "./SupportPersonRow";
import type { SupportPersonDto } from "@/api/types";

const openTelegramLink = vi.fn();

vi.mock("@/lib/tg", () => ({
  openTelegramLink: (url: string) => openTelegramLink(url),
}));

const basePerson: SupportPersonDto = {
  id: 1,
  user_id: 1,
  username: "admin1",
  display_name: "Admin",
  photo_url: null,
  admin: 1,
  prefix: "admin",
};

describe("<SupportPersonRow />", () => {
  it("opens Telegram when username is present", async () => {
    const user = userEvent.setup();
    render(<SupportPersonRow person={basePerson} />);
    await user.click(screen.getByRole("button"));
    expect(openTelegramLink).toHaveBeenCalledWith("https://t.me/admin1");
  });

  it("disables the row when username is missing", () => {
    render(<SupportPersonRow person={{ ...basePerson, username: null }} />);
    expect(screen.getByRole("button")).toBeDisabled();
    expect(screen.getByText("Telegram недоступен")).toBeInTheDocument();
    expect(screen.queryByText("@null")).not.toBeInTheDocument();
  });

  it("disables the row when username is malformed", async () => {
    const user = userEvent.setup();
    openTelegramLink.mockClear();
    render(<SupportPersonRow person={{ ...basePerson, username: "admin/name" }} />);
    const row = screen.getByRole("button");

    expect(row).toBeDisabled();
    await user.click(row);
    expect(openTelegramLink).not.toHaveBeenCalled();
  });
});
