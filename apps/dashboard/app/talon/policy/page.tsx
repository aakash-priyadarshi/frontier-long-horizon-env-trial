"use client";

import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { DataTable, ErrorState, LoadingState, PageHeader } from "@/components/ui";
import { TalonBoundaryNotice, TalonSubnav } from "@/components/talon";
import { MotionButton } from "@/components/motion";

type Policy = {
  policy_gate_version: string;
  actions: string[];
  policy_profiles: Array<{
    profile_id: string;
    jurisdiction: string;
    human_approval_mandatory: boolean;
    allow_response_recommendation: boolean;
  }>;
  constraints: Record<string, boolean>;
};

type ApprovalDemo = {
  mode: string;
  first_use: { accepted: boolean };
  replay: { accepted: boolean; reason_code: string } | null;
  external_effect: boolean;
  gate_rejection: {
    accepted: boolean;
    violation_codes: string[];
    external_effect: boolean;
  };
};

export default function TalonPolicyPage() {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [error, setError] = useState("");
  const [demo, setDemo] = useState<ApprovalDemo | null>(null);

  useEffect(() => {
    api<Policy>("/api/drone/policy")
      .then(setPolicy)
      .catch(reason => setError(reason instanceof Error ? reason.message : String(reason)));
  }, []);

  async function runDemo(mode: "valid" | "replay") {
    try {
      setDemo(await api<ApprovalDemo>("/api/drone/policy/approval-demo", {
        method: "POST",
        body: JSON.stringify({ mode }),
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  return <>
    <PageHeader eyebrow="Deterministic authority" title="Policy gate" description="Every learned recommendation is checked independently of operational reward." />
    <TalonBoundaryNotice />
    <TalonSubnav />
    {error ? <ErrorState message={error} /> : !policy ? <LoadingState rows={4} /> : <>
      <section className="surface-section">
        <div className="section-head">
          <div><span className="eyebrow">{policy.policy_gate_version}</span><h2>Abstract action vocabulary</h2></div>
          <ShieldCheck size={19} />
        </div>
        <DataTable
          caption="Safe Talon action vocabulary"
          headers={["Action ID", "External effect"]}
          rows={policy.actions.map(action => [<code key={action}>{action}</code>, "None · recommendation only"])}
        />
      </section>
      <section className="two-column">
        <article className="surface-section">
          <h2>Non-compensable constraints</h2>
          <ul className="policy-list">
            <li>Authority level and active-track identity bind every escalation.</li>
            <li>Consequential recommendations require fresh causal evidence.</li>
            <li>Command-link state requires the dedicated verification action; general sensor confirmation cannot reveal it.</li>
            <li>Possible crewed aircraft and unresolved sensor disagreement fail closed.</li>
            <li>Authorised and emergency-service flights require safe stand-down.</li>
            <li>Stale tracks, nearby people, revocation, and operator unavailability block response recommendation.</li>
          </ul>
        </article>
        <article className="surface-section">
          <h2>One-time human approval</h2>
          <p>The highest abstract recommendation requires an integrity-protected approval bound to the episode, active track, action, policy version, state revision, and expiry. It is consumed once and never selects or executes a physical mechanism.</p>
          <div className="button-row">
            <MotionButton className="button secondary" onClick={() => void runDemo("valid")}>Run valid approval demo</MotionButton>
            <MotionButton className="button secondary" onClick={() => void runDemo("replay")}>Test replay rejection</MotionButton>
          </div>
          {demo && <div className="notice">
            <strong>{demo.first_use.accepted ? "First use accepted" : "First use rejected"}</strong>
            <p>{demo.replay ? `Replay rejected: ${demo.replay.reason_code}` : "Approval consumed once."} External effect: {String(demo.external_effect)}.</p>
            <p><strong>Gate rejection:</strong> {demo.gate_rejection.accepted ? "unexpected acceptance" : demo.gate_rejection.violation_codes.join(", ")}. External effect: {String(demo.gate_rejection.external_effect)}.</p>
          </div>}
          <div className="constraint-badges">
            {Object.entries(policy.constraints).map(([name, value]) => <span key={name} className={value ? "success" : "muted"}><code>{name}</code>: {String(value)}</span>)}
          </div>
        </article>
      </section>
    </>}
  </>;
}
