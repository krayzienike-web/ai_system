// The chat's stream (Server-Sent Events, docs/08): statuses while the assistant looks at the data, then the answer.
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, parseEvents, stream } from "./client";

function sse(chunks: string[], status = 200): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(new TextEncoder().encode(c));
      controller.close();
    },
  });
  return new Response(body, { status, headers: { "Content-Type": "text/event-stream" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("the chat stream", () => {
  it("parses events with JSON data", () => {
    expect(parseEvents('event: status\ndata: {"text":"Смотрю находки"}\n\nevent: answer\ndata: {"text":"Ок"}\n\n')).toEqual([
      { event: "status", data: { text: "Смотрю находки" } },
      { event: "answer", data: { text: "Ок" } },
    ]);
  });

  it("reports statuses and resolves with the answer, even split across chunks", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => sse(['event: status\ndata: {"text":"Смотрю', ' находки"}\n\nevent: answer\ndata: {"text":"Ок"}\n\n'])),
    );
    const statuses: string[] = [];
    await expect(stream("/chat/stream", { question: "?" }, (s) => statuses.push(s))).resolves.toEqual({ text: "Ок" });
    expect(statuses).toEqual(["Смотрю находки"]);
  });

  it("rejects with the status of an error event and when the stream breaks off", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => sse(['event: error\ndata: {"detail":"Лимит","status":429}\n\n'])));
    await expect(stream("/chat/stream", {}, () => {})).rejects.toMatchObject({ status: 429, message: "Лимит" });
    vi.stubGlobal("fetch", vi.fn(async () => sse(['event: status\ndata: {"text":"…"}\n\n'])));
    await expect(stream("/chat/stream", {}, () => {})).rejects.toBeInstanceOf(ApiError);
  });
});
