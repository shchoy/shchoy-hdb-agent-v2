import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { AskScreen } from "@/app/AskScreen";
import { server } from "@/test/msw";
import { fixture, sseResponse } from "@/test/sse";

const QUESTION = "When do we issue a letter of demand?";

function threadsApi() {
  return http.post("/api/threads", () => HttpResponse.json({ thread_id: "t1" }, { status: 201 }));
}

async function ask(question = QUESTION) {
  const user = userEvent.setup();
  render(<AskScreen />);
  await user.type(screen.getByLabelText("Your question"), question);
  await user.click(screen.getByRole("button", { name: "Ask" }));
  return user;
}

/** Waits until the run is over: Ask is enabled again. */
async function runFinished() {
  await waitFor(() => expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled());
}

describe("Ask screen", () => {
  it("streams the answer and shows the trajectory finished", async () => {
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", () => sseResponse(fixture("answer"))),
    );

    await ask();
    await runFinished();

    const answer = screen.getByRole("region", { name: "Answer" });
    expect(within(answer).getByText("POL-003 v2.0").tagName).toBe("STRONG");
    expect(answer).toHaveTextContent(
      "Under POL-003 v2.0, a letter of demand is issued once arrears reach 60 days.",
    );
    const trajectory = screen.getByRole("list", { name: "Trajectory" });
    expect(within(trajectory).getByRole("listitem")).toHaveTextContent("merge ✓ finished");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("sends the question to the run on a new thread", async () => {
    const requests: { thread: string; body: unknown }[] = [];
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", async ({ params, request }) => {
        requests.push({ thread: String(params.id), body: await request.json() });
        return sseResponse(fixture("answer"));
      }),
    );

    await ask();

    await screen.findByText(/arrears reach 60 days/);
    expect(requests).toEqual([{ thread: "t1", body: { message: QUESTION } }]);
  });

  it("reuses the thread for a follow-up question", async () => {
    let threadsCreated = 0;
    const threads: string[] = [];
    server.use(
      http.post("/api/threads", () => {
        threadsCreated += 1;
        return HttpResponse.json({ thread_id: `t${threadsCreated}` }, { status: 201 });
      }),
      http.post("/api/threads/:id/runs", ({ params }) => {
        threads.push(String(params.id));
        return sseResponse(fixture("answer"));
      }),
    );

    const user = await ask();
    await runFinished();
    await user.type(screen.getByLabelText("Your question"), "And after that?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await runFinished();

    expect(threadsCreated).toBe(1);
    expect(threads).toEqual(["t1", "t1"]);
  });

  it("warns that the answer is incomplete on an error event and Retry re-asks", async () => {
    const asked: unknown[] = [];
    let call = 0;
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", async ({ request }) => {
        asked.push(await request.json());
        call += 1;
        return sseResponse(fixture(call === 1 ? "error" : "answer"));
      }),
    );

    const user = await ask();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/incomplete and must not be trusted/);
    expect(screen.queryByText(/a letter of$/)).not.toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByText(/arrears reach 60 days/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(asked).toEqual([{ message: QUESTION }, { message: QUESTION }]);
  });

  it("shows the error alert when a frame is malformed", async () => {
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", () =>
        sseResponse('id: 1\r\nevent: token\r\ndata: {"type":"token","seq":"x"}\r\n\r\n'),
      ),
    );

    await ask();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /incomplete and must not be trusted/,
    );
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("shows the error alert when the stream ends without finishing", async () => {
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", () =>
        sseResponse(fixture("answer").split("event: done")[0]),
      ),
    );

    await ask();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /incomplete and must not be trusted/,
    );
  });

  it("shows the error alert when the run request fails", async () => {
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", () =>
        HttpResponse.json({ detail: "boom" }, { status: 502 }),
      ),
    );

    await ask();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /incomplete and must not be trusted/,
    );
  });

  it("shows the error alert when the network is down", async () => {
    server.use(threadsApi(), http.post("/api/threads/:id/runs", () => HttpResponse.error()));

    await ask();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("disables Ask while the answer is streaming", async () => {
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", () => sseResponse(fixture("answer"))),
    );

    await ask();

    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    await runFinished();
    expect(screen.getByText(/arrears reach 60 days/)).toBeInTheDocument();
  });
});
