import { act, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import RunPage from "@/app/runs/[runId]/page";

const defaultEventSource = globalThis.EventSource;

function response(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) } as Response);
}

class LiveEventSource {
  static instance: LiveEventSource | null = null;
  onopen: (() => void) | null = null;
  onmessage: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners = new Map<string, (event: MessageEvent<string>) => void>();
  close = vi.fn();

  constructor() { LiveEventSource.instance = this; }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
    this.listeners.set(type, listener as (event: MessageEvent<string>) => void);
  }

  emit(type: string, data: unknown) {
    this.listeners.get(type)?.(new MessageEvent(type, { data: JSON.stringify(data) }));
  }
}

afterEach(() => {
  globalThis.EventSource = defaultEventSource;
  LiveEventSource.instance = null;
});

test("appends completed environment actions directly from the live run stream", async () => {
  const run = {
    run_id: "run-test", batch_id: "batch-test", status: "running",
    provider: "ollama", model: "llama3.1:8b", split: "eval", seed: 0, attempt: 1,
    current_step: 0, action_count: 0, model_call_count: 1, input_tokens: 100, output_tokens: 10,
    authenticated_timeline: [], candidate_diff_summary: { changed_paths: [], file_count: 0 },
  };
  const fetchMock = vi.fn(() => response(run));
  vi.stubGlobal("fetch", fetchMock);
  globalThis.EventSource = LiveEventSource as unknown as typeof EventSource;

  render(<RunPage />);
  expect(await screen.findByRole("heading", { name: "Action timeline" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Download JSON" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Waiting for the first action" })).toBeInTheDocument();
  await waitFor(() => expect(LiveEventSource.instance).not.toBeNull());
  act(() => LiveEventSource.instance?.onopen?.());
  expect(screen.getByText("Live actions connected")).toBeInTheDocument();

  const timelineEntry = {
    sequence: 1, fake_tick: 45, tool: "release.status", arguments: {},
    result_summary: { active_revision: "r1" }, request_bytes: 2, response_bytes: 25,
    duration_ms: 12.5, success: true, error_code: null, terminated: false, truncated: false,
  };
  act(() => LiveEventSource.instance?.emit("tool_completed", {
    current_step: 1, input_tokens: 200, output_tokens: 20, timeline_entry: timelineEntry,
  }));

  const timeline = screen.getByRole("heading", { name: "Action timeline" }).closest("section")!;
  expect(await within(timeline).findByText("release.status")).toBeInTheDocument();
  expect(within(timeline).getByText("Latest live action")).toBeInTheDocument();
  expect(screen.getByText("Step 1")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);

  act(() => LiveEventSource.instance?.emit("tool_completed", {
    current_step: 1, input_tokens: 200, output_tokens: 20, timeline_entry: timelineEntry,
  }));
  expect(within(timeline).getAllByText("release.status")).toHaveLength(1);
});
