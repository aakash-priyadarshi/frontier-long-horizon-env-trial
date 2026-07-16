import { downloadEpisodeJson, episodeJson } from "@/lib/episode-export";
import type { Run } from "@/lib/types";

const run = {
  run_id: "run_shareable",
  batch_id: "batch_shareable",
  status: "completed",
  provider: "anthropic",
  model: "claude-fable-5",
  split: "eval",
  seed: 0,
  attempt: 1,
  authenticated_timeline: [{
    sequence: 1,
    tool: "release.status",
    arguments: {},
    result_summary: { incident: "open" },
    request_bytes: 2,
    response_bytes: 19,
    duration_ms: 12,
    success: true,
    terminated: false,
    truncated: false,
  }],
  model_turn_debug: [{
    turn: 1,
    finish_reason: "tool_use",
    tool_call_count: 1,
    tool_names: ["release.status"],
    dropped_tool_calls: 0,
    has_text: false,
    text_chars: 0,
    has_reasoning: true,
    reasoning_chars: 128,
    input_tokens: 100,
    output_tokens: 40,
    reasoning_tokens: 0,
    latency_ms: 250,
  }],
} satisfies Run;

test("serializes the complete sanitized episode object without changing it", () => {
  expect(JSON.parse(episodeJson(run))).toEqual(run);
  expect(episodeJson(run)).not.toContain("api_key");
});

test("downloads a run-id named JSON file", () => {
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  downloadEpisodeJson(run);
  expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
  expect(click).toHaveBeenCalledOnce();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:test-export");
});
