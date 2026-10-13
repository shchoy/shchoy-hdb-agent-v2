import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { SignInForm } from "@/app/sign-in/SignInForm";
import { server } from "@/test/msw";

const push = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh }) }));

const personas = [
  { staff_id: "S01", name: "Tan Wei Ling", title: "Director", dept: "PLG", role: "director" },
  { staff_id: "S04", name: "Marcus Lim", title: "Estate Manager", dept: "PLG", role: "estate_manager" },
] as const;

describe("Sign-in", () => {
  it("posts the chosen persona's staff ID to the session and goes to the Ask screen", async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post("/api/session", async ({ request }) => {
        bodies.push(await request.json());
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(<SignInForm personas={[...personas]} />);

    await userEvent.click(screen.getByRole("button", { name: /Marcus Lim/ }));

    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/"));
    expect(bodies).toEqual([{ staff_id: "S04" }]);
  });

  it("lists each persona with title and role", () => {
    render(<SignInForm personas={[...personas]} />);

    expect(screen.getByRole("button", { name: /Marcus Lim/ })).toHaveTextContent(
      /Estate Manager.*estate manager/,
    );
  });

  it("shows an alert when sign-in is refused", async () => {
    server.use(
      http.post("/api/session", () =>
        HttpResponse.json({ detail: "Unknown staff ID" }, { status: 401 }),
      ),
    );
    render(<SignInForm personas={[...personas]} />);

    await userEvent.click(screen.getByRole("button", { name: /Tan Wei Ling/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not sign you in/i);
  });
});
