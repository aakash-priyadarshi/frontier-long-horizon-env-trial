export type EvaluationPresetId = "smoke" | "balanced" | "confidence";

export type EvaluationPresetValues = {
  split: "eval";
  seedStart: number;
  seedCount: number;
  attempts: number;
  concurrency: number;
  temperature: number;
  maxTokens: number;
  contextWindow: number;
  reasoning: "low" | "medium";
  timeout: number;
  retries: number;
  maxSteps: number;
  maxCalls: number;
  wallClock: number;
  deterministic: boolean;
};

export const EVALUATION_PRESETS: ReadonlyArray<{
  id: EvaluationPresetId;
  label: string;
  description: string;
  episodeSummary: string;
}> = [
  {
    id: "smoke",
    label: "Quick smoke",
    description: "Confirm connectivity, tool calling, and the end-to-end verifier flow.",
    episodeSummary: "1 seed × 1 attempt",
  },
  {
    id: "balanced",
    label: "Balanced",
    description: "A practical first comparison with repeat attempts across several seeds.",
    episodeSummary: "5 seeds × 2 attempts",
  },
  {
    id: "confidence",
    label: "Confidence run",
    description: "More coverage and repeatability evidence for a model you have already tested.",
    episodeSummary: "10 seeds × 3 attempts",
  },
];

export function evaluationPresetValues(id: EvaluationPresetId, provider: string): EvaluationPresetValues {
  const local = provider === "ollama";
  const preset = {
    smoke: {
      seedCount: 1,
      attempts: 1,
      concurrency: 1,
      maxTokens: 2048,
      contextWindow: 16384,
      reasoning: "low" as const,
      timeout: local ? 180 : 60,
      retries: 1,
      wallClock: local ? 1800 : 600,
    },
    balanced: {
      seedCount: 5,
      attempts: 2,
      concurrency: local ? 1 : 2,
      maxTokens: 4096,
      contextWindow: 16384,
      reasoning: "medium" as const,
      timeout: local ? 240 : 90,
      retries: 2,
      wallClock: local ? 2400 : 900,
    },
    confidence: {
      seedCount: 10,
      attempts: 3,
      concurrency: local ? 1 : 4,
      maxTokens: 4096,
      contextWindow: 16384,
      reasoning: "medium" as const,
      timeout: local ? 300 : 120,
      retries: 2,
      wallClock: local ? 3600 : 1200,
    },
  }[id];

  return {
    split: "eval",
    seedStart: 0,
    temperature: 0,
    maxSteps: 64,
    maxCalls: 64,
    deterministic: true,
    ...preset,
  };
}
