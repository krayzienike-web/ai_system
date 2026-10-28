// The chat's stream (Server-Sent Events, docs/08): statuses while the assistant looks at the data, then the answer.
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, parseEvents, stream } from "./client";

function sse(chunks: (string | Uint8Array)[], status = 200): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(typeof c === "string" ? new TextEncoder().encode(c) : c);
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

  it("survives a character split between chunks, a blank line split in two, CRLF and keep-alives", async () => {
    const bytes = new TextEncoder().encode('event: status\r\ndata: {"text":"Смотрю"}\r\n\r\n: ping\n\nevent: answer\ndata: {"text":"Ок"}\n');
    const cut = bytes.indexOf(0xd0, 30) + 1; // inside the two bytes of a Cyrillic letter
    vi.stubGlobal("fetch", vi.fn(async () => sse([bytes.slice(0, cut), bytes.slice(cut, -1), bytes.slice(-1), "\n"])));
    const statuses: string[] = [];
    await expect(stream("/chat/stream", {}, (s) => statuses.push(s))).resolves.toEqual({ text: "Ок" });
    expect(statuses).toEqual(["Смотрю"]);
  });

  it("refreshes the token once on 401 and asks again", async () => {
    const store = new Map([["fai.refresh", "r1"]]);
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => store.set(k, v),
      removeItem: (k: string) => store.delete(k),
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: "a2", refresh_token: "r2" }), { status: 200 }))
      .mockResolvedValueOnce(sse(['event: answer\ndata: {"text":"Ок"}\n\n']));
    vi.stubGlobal("fetch", fetchMock);
    await expect(stream("/chat/stream", {}, () => {})).resolves.toEqual({ text: "Ок" });
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/auth/refresh");
    expect(new Headers((fetchMock.mock.calls[2]?.[1] as RequestInit).headers).get("Authorization")).toBe("Bearer a2");
  });

  it("stops reading when the chat is closed", async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_: string, init: RequestInit) => {
        controller.abort();
        if (init.signal?.aborted) throw new DOMException("aborted", "AbortError");
        return sse([]);
      }),
    );
    await expect(stream("/chat/stream", {}, () => {}, controller.signal)).rejects.toMatchObject({ name: "AbortError" });
  });
});
