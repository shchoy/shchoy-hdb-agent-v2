// @vitest-environment node
import { describe, expect, it } from "vitest";
import { InvalidFrameError, parseRunEvents, type RunEvent } from "@/lib/events";

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>): Promise<RunEvent[]> {
  const events: RunEvent[] = [];
  for await (const event of parseRunEvents(stream)) events.push(event);
  return events;
}

const done = '{"type":"done","seq":2,"run_id":"r1"}';

describe("parseRunEvents", () => {
  it("reads frames whose CRLF line endings are split across chunks", async () => {
    const events = await collect(
      streamOf(
        'id: 1\r\nevent: token\r\ndata: {"type":"token","seq":1,"node":"merge","text":"Hi"}\r',
        "\n\r",
        `\nid: 2\r\nevent: done\r\ndata: ${done}\r\n\r\n`,
      ),
    );
    expect(events).toEqual([
      { type: "token", seq: 1, node: "merge", text: "Hi" },
      { type: "done", seq: 2, run_id: "r1" },
    ]);
  });

  it("ignores heartbeat comments", async () => {
    const events = await collect(streamOf(`: ping\r\n\r\nevent: done\r\ndata: ${done}\r\n\r\n`));
    expect(events).toEqual([{ type: "done", seq: 2, run_id: "r1" }]);
  });

  it("joins multi-line data with newlines", async () => {
    const events = await collect(
      streamOf('data: {"type":"done",\ndata: "seq":2,"run_id":"r1"}\n\n'),
    );
    expect(events).toEqual([{ type: "done", seq: 2, run_id: "r1" }]);
  });

  it("rejects a frame that is not a RunEvent", async () => {
    await expect(
      collect(streamOf('event: token\r\ndata: {"type":"token","seq":"one"}\r\n\r\n')),
    ).rejects.toBeInstanceOf(InvalidFrameError);
  });

  it("rejects a frame that is not JSON", async () => {
    await expect(collect(streamOf("data: not json\n\n"))).rejects.toBeInstanceOf(
      InvalidFrameError,
    );
  });
});
