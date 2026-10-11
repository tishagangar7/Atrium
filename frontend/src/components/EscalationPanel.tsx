import { Icon } from "./Icon";
import {
  agentNames,
  authoritativeEval,
  planLabel,
  type IncidentModel,
} from "../incident";
import type { AgentId, EscalationPackage } from "../types";

// PRD §9.7: only feasible candidates from the package plus F0. The UI never ranks or picks;
// it forwards the human's click to POST /escalations/{dp_id}/resolve (FR-051).
interface Props {
  escalation: EscalationPackage;
  incident: IncidentModel;
  disabledReason: string | null;
  pending: boolean;
  onChoose: (choice: "candidate" | "fallback", planHash?: string) => void;
}

const triggers: Record<EscalationPackage["trigger"], string> = {
  ROUNDS_EXHAUSTED: "No agreement after all rounds",
  BUDGET_EXCEEDED: "Time budget ran out",
  ALL_ESCALATED: "All agents asked for a human",
  AGENT_UNAVAILABLE: "An agent became unavailable",
};

const percent = (value: number | null | undefined) =>
  value == null ? "N/A" : `${Math.round(value * 100)}%`;

export function EscalationPanel({
  escalation,
  incident,
  disabledReason,
  pending,
  onChoose,
}: Props) {
  const unmet = (Object.entries(escalation.unmet_targets ?? {}) as [
    AgentId,
    string[],
  ][]).filter(([, metrics]) => metrics.length > 0);
  const disabled = pending || disabledReason !== null;

  return (
    <section className="escalation" aria-labelledby="escalation-heading">
      <header>
        <Icon name="info" size={18} />
        <div>
          <h2 id="escalation-heading">A human decision is needed</h2>
          <p>
            {triggers[escalation.trigger] ?? escalation.trigger} ·{" "}
            {escalation.dp_id}. The agents did not agree, so nothing has been
            committed.
          </p>
        </div>
      </header>

      <div className="escalation-facts">
        {escalation.blocking_constraints.length > 0 && (
          <div>
            <span>Blocking</span>
            <strong>{escalation.blocking_constraints.join(", ")}</strong>
          </div>
        )}
        {unmet.length > 0 && (
          <div>
            <span>Unmet targets</span>
            <strong>
              {unmet
                .map(([agent, metrics]) => `${agentNames[agent]}: ${metrics.join(", ").replace(/_/g, " ")}`)
                .join(" · ")}
            </strong>
          </div>
        )}
      </div>

      <ul className="escalation-options">
        {escalation.candidates.map((hash) => {
          const plan = incident.plans[hash];
          const evaluation = authoritativeEval(incident, hash);
          return (
            <li key={hash}>
              <div>
                <strong>
                  {plan ? planLabel(plan, incident.dpId) : hash.slice(0, 12)}
                  {plan && <span> by {agentNames[plan.proposer]}</span>}
                </strong>
                <span>
                  Assisted {percent(evaluation?.metrics?.assisted_completion)} · fire{" "}
                  {evaluation?.metrics ? `${evaluation.metrics.fire_extent} cells` : "—"} ·
                  forecast · simulator
                </span>
              </div>
              <button
                className="secondary-button"
                disabled={disabled}
                onClick={() => onChoose("candidate", hash)}
              >
                Choose this plan
              </button>
            </li>
          );
        })}
        <li>
          <div>
            <strong>Fallback F0</strong>
            <span>Keep legs already under way; everything else holds.</span>
          </div>
          <button
            className="secondary-button"
            disabled={disabled}
            onClick={() => onChoose("fallback")}
          >
            Use fallback
          </button>
        </li>
      </ul>

      <p className="escalation-rule">
        You can change priorities. You cannot add vehicles or open closed roads.
        {" "}Relaxing targets becomes available once agent targets are in the
        snapshot.
      </p>
      {disabledReason && <p className="fine-print">{disabledReason}</p>}
    </section>
  );
}
