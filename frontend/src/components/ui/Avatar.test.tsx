import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Avatar } from "./Avatar";

describe("<Avatar />", () => {
  it("renders the first letter of the name when no image is given", () => {
    render(<Avatar name="alice" />);
    expect(screen.getByText("A")).toBeInTheDocument();
  });

  it("strips a leading @ when computing the letter", () => {
    render(<Avatar name="@bob" />);
    expect(screen.getByText("B")).toBeInTheDocument();
  });

  it('falls back to "?" for missing/blank names', () => {
    render(<Avatar name="" />);
    expect(screen.getByText("?")).toBeInTheDocument();
  });

  it("renders an <img> when src is provided", () => {
    render(<Avatar name="carol" src="https://example.com/a.png" />);
    const img = screen.getByRole("img", { name: "carol" });
    expect(img).toHaveAttribute("src", "https://example.com/a.png");
    expect(img).toHaveAttribute("loading", "lazy");
  });

  it.each([
    "javascript:alert(1)",
    "data:image/svg+xml,<svg onload=alert(1)>",
    "http://example.com/a.png",
    "https://example.com@evil.example/a.png",
    "/media/avatar//a.png",
  ])("renders the letter fallback for unsafe src %s", (src) => {
    render(<Avatar name="mallory" src={src} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("M")).toBeInTheDocument();
  });
});
