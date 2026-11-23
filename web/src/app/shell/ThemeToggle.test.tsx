import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { server } from "@/test/msw";
import { inShell } from "@/test/shell";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

function themeCookie(): string | undefined {
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith("plg_theme="))
    ?.slice("plg_theme=".length);
}

beforeEach(() => {
  document.cookie = "plg_theme=; path=/; max-age=0";
  delete document.documentElement.dataset.theme;
  server.use(
    http.get("/api/threads", () => HttpResponse.json([])),
    http.get("/api/approvals", () => HttpResponse.json([])),
  );
});

describe("Theme toggle", () => {
  it("offers Light, Dark and System in the sidebar, System chosen by default", () => {
    render(inShell(<p>screen</p>));

    const group = screen.getByRole("radiogroup", { name: "Theme" });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "System" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Light" })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: "Dark" })).not.toBeChecked();
  });

  it("shows the saved choice the server rendered", () => {
    document.documentElement.dataset.theme = "dark";
    render(inShell(<p>screen</p>, undefined, "dark"));

    expect(screen.getByRole("radio", { name: "Dark" })).toBeChecked();
  });

  it("switches the theme at once and remembers it", async () => {
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));

    await user.click(screen.getByRole("radio", { name: "Dark" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(themeCookie()).toBe("dark");

    await user.click(screen.getByRole("radio", { name: "Light" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(themeCookie()).toBe("light");
  });

  it("System forgets the choice and follows the OS again", async () => {
    document.documentElement.dataset.theme = "light";
    const user = userEvent.setup();
    render(inShell(<p>screen</p>, undefined, "light"));

    await user.click(screen.getByRole("radio", { name: "System" }));
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(themeCookie()).toBeUndefined();
  });
});
