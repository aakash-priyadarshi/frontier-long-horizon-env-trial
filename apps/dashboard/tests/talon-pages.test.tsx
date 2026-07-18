import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import TalonOverviewPage from "@/app/talon/page";
import TalonScenariosPage from "@/app/talon/scenarios/page";
import TalonPolicyPage from "@/app/talon/policy/page";
import TalonTrainingRunPage from "@/app/talon/training/[runId]/page";
import TalonEvaluationPage from "@/app/talon/evaluations/[evaluationId]/page";

function response(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) } as Response);
}

test("Talon overview stays visibly simulation-only", async () => {
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    if (url.includes("/health")) return response({ total_records: 2, completed_evaluations: 1, active_records: 0, torch_available: true });
    if (url.includes("/scenarios")) return response({ total: 5, items: [] });
    return response({ items: [] });
  }));
  render(<TalonOverviewPage />);
  expect(await screen.findByText("5")).toBeInTheDocument();
  expect(screen.getByText("Simulation-only decision support")).toBeInTheDocument();
  expect(screen.getByText(/No physical-response controls exist here/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Review the policy gate/ })).toBeInTheDocument();
});

test("capability browser never renders private scenario labels", async () => {
  vi.stubGlobal("fetch", vi.fn(() => response({ items: [{ capability_id: "identity_evidence", title: "Identity evidence", public_summary: "Resolve uncertain identities with bounded public evidence.", safety_focus: ["classification", "remote_id"] }] })));
  render(<TalonScenariosPage />);
  expect(await screen.findByRole("heading", { name: "Identity evidence" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Public temporal evidence" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Strict verification boundary" })).toBeInTheDocument();
  expect(document.body.textContent).not.toMatch(/authorised_inspection|paired|expected_action|scenario family:/i);
});

test("policy page exposes only abstract no-effect actions and scoped approval", async () => {
  vi.stubGlobal("fetch", vi.fn(() => response({
    policy_gate_version: "talon.policy-gate/2.0",
    actions: ["CONTINUE_OBSERVATION", "REQUEST_RESPONSE_AUTHORISATION", "RECOMMEND_AUTHORISED_MITIGATION"],
    policy_profiles: [],
    constraints: { simulation_only: true, decision_support_only: true, external_effect: false, human_approval_mandatory: true, physical_countermeasure_selection: false },
  })));
  render(<TalonPolicyPage />);
  expect(await screen.findByText("REQUEST_RESPONSE_AUTHORISATION")).toBeInTheDocument();
  expect(screen.getAllByText("None · recommendation only")).toHaveLength(3);
  expect(screen.getByText(/bound to the episode, active track, action, policy version/)).toBeInTheDocument();
});

test("training detail labels accuracy as in-sample and exposes only public metadata", async () => {
  vi.stubGlobal("fetch", vi.fn(() => response({
    record_id: "run-test", kind: "training", status: "completed", architecture: "gru", parameter_count: 1234,
    progress: { phase: "completed", epoch: 2, epochs: 2, loss: 0.1, training_action_accuracy: 1 },
    training_history: { loss: [0.8, 0.1], training_action_accuracy: [0.5, 1] },
    training_metrics: { loss: 0.1, training_action_accuracy: 1, validation_action_accuracy: 0.75 },
    checkpoint_digest: `sha256:${"a".repeat(64)}`, record_digest: `sha256:${"d".repeat(64)}`,
  })));
  render(<TalonTrainingRunPage />);
  expect(await screen.findByTestId("line-chart")).toBeInTheDocument();
  expect(screen.getByText("100.0%")).toBeInTheDocument();
  expect(screen.getByText("In-sample; not held-out safety")).toBeInTheDocument();
  expect(screen.getByText("75.0%")).toBeInTheDocument();
  expect(screen.getByText("Digest-bound")).toBeInTheDocument();
  expect(document.body.textContent).not.toMatch(/scenario_family|instance_digest|expert_action/i);
});

test("evaluation timeline displays only opaque episodes and high-level categories", async () => {
  vi.stubGlobal("fetch", vi.fn(() => response({
    record_id: "talon-eval-test", kind: "evaluation", status: "completed",
    aggregate: { episode_count: 1, strict_success_count: 0, strict_success_rate: 0, safety_violation_count: 1, safety_violation_rate: 1, average_score: 0, abstention_rate: 1, false_escalation_rate: 0, missed_threat_rate: 1, expected_calibration_error: 0.9, held_out_action_accuracy: 0.25 },
    episodes: [{
      schema_version: "talon.public-evaluation-episode/2.0", evaluation_id: "episode-1", checkpoint_digest: `sha256:${"b".repeat(64)}`, environment_version: "talon.environment/2.0", verifier_version: "talon.verifier/2.0",
      result: { episode_id: `ep_${"a".repeat(24)}`, score: 0, strict_success: false, verdict: "fail", safety_violation_count: 1, failed_categories: ["protected-identity"], action_count: 1, result_digest: `sha256:${"c".repeat(64)}`, expected_calibration_error: 0.9, confidence_calibration_bins: [{ lower: 0.8, upper: 1, count: 1, mean_confidence: 0.9, gate_acceptance_rate: 0 }] },
      timeline: [{ sequence: 1, observation: { episode_id: `ep_${"a".repeat(24)}` }, recommendation: { recommended_action: "REQUEST_RESPONSE_AUTHORISATION", action_confidence: 0.9, uncertainty: 0.1, reason_codes: [] }, gate: { accepted: false, requested_action: "REQUEST_RESPONSE_AUTHORISATION", effective_action: "ABSTAIN_INSUFFICIENT_EVIDENCE", violation_codes: ["crewed_aircraft_response_prohibited"], human_approval_required: true, external_effect: false }, public_reward: 0, terminated: true, truncated: false }],
    }],
  })));
  render(<TalonEvaluationPage />);
  expect(await screen.findByText(/rejected: crewed_aircraft_response_prohibited/)).toBeInTheDocument();
  expect(screen.getByText("ABSTAIN_INSUFFICIENT_EVIDENCE")).toBeInTheDocument();
  expect(screen.getByText("protected-identity")).toBeInTheDocument();
  expect(screen.getAllByText("Confidence calibration").length).toBeGreaterThan(0);
  expect(document.body.textContent).not.toMatch(/scenario_famil|failed_predicate|expected_action|seed 0/i);
  expect(screen.queryByRole("button", { name: /engage|disable|jam/i })).not.toBeInTheDocument();
});
