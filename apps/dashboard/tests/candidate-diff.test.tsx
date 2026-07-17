import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import RunPage from "@/app/runs/[runId]/page";
import type { Run } from "@/lib/types";

function response(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) } as Response);
}

const retainedRun: Run = {
  run_id: "run-test",
  batch_id: "batch-test",
  status: "completed",
  provider: "anthropic",
  model: "claude-fable-5",
  split: "eval",
  seed: 0,
  attempt: 1,
  authoritative_reward: 0.85,
  authoritative_verdict: "partial",
  candidate_diff_summary: {
    changed_paths: ["service/flow.py"],
    file_count: 1,
    retention: {
      captured: true,
      artifact_digest: `sha256:${"a".repeat(64)}`,
      stored_bytes: 512,
      redaction_count: 1,
      truncated: false,
    },
  },
  candidate_diff_storage: {
    state: "available",
    stored_bytes: 512,
    artifact_digest: `sha256:${"a".repeat(64)}`,
  },
  candidate_diff: {
    artifact_version: "1.0",
    artifact_digest: `sha256:${"a".repeat(64)}`,
    format: "unified_diff",
    file_count: 1,
    changed_paths: ["service/flow.py"],
    redaction_count: 1,
    truncated: false,
    files: [{
      path: "service/flow.py",
      before_sha256: `sha256:${"b".repeat(64)}`,
      after_sha256: `sha256:${"c".repeat(64)}`,
      after_bytes: 42,
      diff: "--- a/service/flow.py\n+++ b/service/flow.py\n-old\n+new\n+<redacted-sensitive-line>\n",
      truncated: false,
    }],
  },
  authenticated_timeline: [],
};

test("renders a sanitized digest-bound candidate diff and deletes only its artifact", async () => {
  let available = true;
  const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
    if (init?.method === "DELETE") {
      available = false;
      return response({ run_id: "run-test", deleted: true, reclaimed_bytes: 512 });
    }
    return response(available ? retainedRun : {
      ...retainedRun,
      candidate_diff: undefined,
      candidate_diff_storage: {
        state: "deleted",
        stored_bytes: 0,
        artifact_digest: retainedRun.candidate_diff?.artifact_digest,
      },
    });
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<RunPage />);

  expect(await screen.findByRole("heading", { name: "Candidate diff" })).toBeInTheDocument();
  expect(screen.getAllByText("service/flow.py")).toHaveLength(2);
  expect(screen.getByText(/redacted-sensitive-line/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "View diff" })).toHaveAttribute("href", "#candidate-diff-heading");
  await userEvent.click(screen.getByRole("button", { name: "Delete diff" }));
  expect(screen.getByRole("heading", { name: "Delete retained candidate diff?" })).toBeInTheDocument();
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete diff" }));
  expect(await screen.findByRole("heading", { name: "Candidate diff was deleted" })).toBeInTheDocument();
  expect(screen.getByText(/immutable score record and artifact digest remain/)).toBeInTheDocument();
});

test("explains why a legacy episode cannot expose its exact candidate source", async () => {
  vi.stubGlobal("fetch", vi.fn(() => response({
    ...retainedRun,
    run_id: "run-legacy",
    candidate_diff: undefined,
    candidate_diff_storage: {
      state: "not_captured",
      stored_bytes: 0,
    },
    candidate_diff_summary: {
      changed_paths: ["service/flow.py", "service/settings.toml"],
      file_count: 2,
    },
  })));

  render(<RunPage />);

  expect(await screen.findByText(/predates secure candidate-diff retention/i)).toBeInTheDocument();
  expect(screen.getByText(/exact candidate source cannot be reconstructed/i)).toBeInTheDocument();
  expect(screen.getByText("Legacy run · diff unavailable")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "View diff" })).not.toBeInTheDocument();
});
