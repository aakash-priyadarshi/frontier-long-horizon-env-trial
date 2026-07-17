import type { Run } from "@/lib/types";

export function episodeJson(run: Run): string {
  // The run API is already the security boundary: it contains the complete
  // sanitized episode record and excludes credentials, private reasoning, hidden
  // workloads, and capability material. Serialize that exact object without
  // introducing a second, divergent export schema.
  return `${JSON.stringify(run, null, 2)}\n`;
}

export function downloadEpisodeJson(run: Run): void {
  const blob = new Blob([episodeJson(run)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${run.run_id}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}
