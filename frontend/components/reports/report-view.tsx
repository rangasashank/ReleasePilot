"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import type { AnalysisReport, Evidence, Finding } from "@/lib/api";

const labels = {
  tests: "Tests / CI",
  code_review: "Code / review",
  complexity: "Change complexity",
  documentation: "Deployment documentation",
};

export function RecommendationBadge({
  value,
}: {
  value: AnalysisReport["decision"]["recommendation"];
}) {
  return (
    <span className={`recommendation ${value.toLowerCase()}`}>
      {value.replaceAll("_", " ")}
    </span>
  );
}

function EvidenceDrawer({
  evidence,
  synthetic,
  onClose,
}: {
  evidence: Evidence | null;
  synthetic: boolean;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (evidence) dialog.current?.showModal();
    else dialog.current?.close();
  }, [evidence]);
  return (
    <dialog
      ref={dialog}
      className="evidence-drawer"
      aria-labelledby="evidence-title"
      onClose={onClose}
    >
      {evidence && (
        <>
          <div className="drawer-header">
            <span className="phase-pill">CAPTURED EVIDENCE</span>
            <button
              autoFocus
              className="secondary-button"
              onClick={() => dialog.current?.close()}
              aria-label="Close evidence"
            >
              Close ×
            </button>
          </div>
          <h2 id="evidence-title">{evidence.title}</h2>
          <p className="evidence-locator">{evidence.locator}</p>
          <blockquote>{evidence.excerpt}</blockquote>
          <dl className="evidence-meta">
            <dt>Source type</dt>
            <dd>{evidence.source_type}</dd>
            <dt>Captured at</dt>
            <dd>{evidence.captured_at}</dd>
            <dt>Evidence ID</dt>
            <dd>
              <code>{evidence.id}</code>
            </dd>
          </dl>
          {evidence.url && (
            <a
              className="button"
              href={evidence.url}
              target="_blank"
              rel="noreferrer"
            >
              Open source ↗
            </a>
          )}
          <p className="hint">
            {synthetic
              ? "Synthetic evidence for learning. No live repository was queried."
              : "Captured evidence at analysis time. Later source changes do not rewrite this report."}
          </p>
        </>
      )}
    </dialog>
  );
}

export function ReportView({ report }: { report: AnalysisReport }) {
  const [selected, setSelected] = useState<Evidence | null>(null);
  const { decision } = report;
  const evidenceById = new Map(report.evidence.map((item) => [item.id, item]));
  const sections = [
    { kind: "blocker", title: "Hard blockers" },
    { kind: "warning", title: "Warnings" },
    { kind: "unknown", title: "Missing evidence" },
    { kind: "positive", title: "Positive signals" },
  ] as const;
  function findingCard(finding: Finding) {
    return (
      <article className={`finding-card ${finding.kind}`} key={finding.id}>
        <div className="finding-heading">
          <span className="finding-category">{labels[finding.category]}</span>
          <span className="finding-points">
            {finding.points
              ? `+${finding.points} risk points`
              : finding.kind === "unknown"
                ? "Unknown"
                : "0 risk points"}
          </span>
        </div>
        <h3>{finding.title}</h3>
        <p>{finding.explanation}</p>
        <div className="citations">
          {finding.evidence_ids.map((id) => {
            const evidence = evidenceById.get(id);
            return evidence ? (
              <button
                className="citation-button"
                key={id}
                onClick={() => setSelected(evidence)}
                aria-label={`View evidence: ${evidence.title}`}
              >
                ↗ {evidence.title}
              </button>
            ) : (
              <span className="error" key={id}>
                Evidence unavailable
              </span>
            );
          })}
        </div>
      </article>
    );
  }
  return (
    <>
      <Link href="/dashboard" className="back-link">
        ← Workspace overview
      </Link>
      <div className="page-heading">
        <div>
          <span className="eyebrow">RELEASE REPORT</span>
          <h1>{report.service_name}</h1>
          <p>Saved analysis · {decision.policy_version}</p>
        </div>
        <Link href="/analyses/new" className="button">
          Run another analysis →
        </Link>
      </div>
      {report.source_mode === "demo" && (
        <div className="demo-notice">
          <strong>Fixture data</strong> · This report demonstrates the policy
          engine. It does not assess your service’s real code.
        </div>
      )}
      <section
        className={`report-summary panel decision-${decision.recommendation.toLowerCase()}`}
        aria-label="Release decision"
      >
        <div className="decision-title">
          <RecommendationBadge value={decision.recommendation} />
          <span>Release recommendation</span>
        </div>
        <p>{decision.summary}</p>
        <div className="sha-grid">
          <div>
            <span>BASE COMMIT</span>
            <code>{report.base_sha}</code>
          </div>
          <div>
            <span>EXACT TARGET COMMIT</span>
            <code>{report.head_sha}</code>
          </div>
        </div>
      </section>
      <div className="score-grid">
        <section className="panel score-card">
          <span className="eyebrow">OBSERVED RISK</span>
          <div className="score-number">
            {decision.risk_score}
            <span>/100</span>
          </div>
          <p>Points from deterministic rules. Lower is better.</p>
          {Object.entries(decision.category_caps).map(([category, cap]) => (
            <div className="score-row" key={category}>
              <span>{labels[category as keyof typeof labels]}</span>
              <strong>
                {decision.category_scores[category as keyof typeof labels]} /{" "}
                {cap}
              </strong>
            </div>
          ))}
          <p className="hint">
            Category totals are capped; individual finding points may sum above
            the cap. Complexity signals are heuristics.
          </p>
        </section>
        <section
          className={`panel score-card ${decision.confidence_score < 75 ? "low-confidence" : ""}`}
        >
          <span className="eyebrow">EVIDENCE CONFIDENCE</span>
          <div className="score-number">
            {decision.confidence_score}
            <span>/100</span>
          </div>
          <p>
            {decision.confidence_score < 75
              ? "Low confidence — missing evidence prevents GO."
              : "Evidence coverage, not a probability of success."}
          </p>
          {decision.confidence_components.map((component) => (
            <div key={component.category} className="confidence-row">
              <div>
                <span>
                  {component.category === "ci"
                    ? "CI / checks"
                    : component.category}
                </span>
                <strong>
                  {component.earned} / {component.weight}
                </strong>
              </div>
              <small>{component.reason}</small>
            </div>
          ))}
          <p className="hint">
            GO requires confidence ≥75, risk &lt;30, passing required checks,
            complete mandatory evidence, and no hard blocker.
          </p>
        </section>
      </div>
      {sections.map((section) => {
        const findings = decision.findings.filter(
          (item) => item.kind === section.kind,
        );
        return (
          <section
            key={section.kind}
            aria-label={section.title}
            className="report-section"
          >
            <div className="section-heading">
              <h2>{section.title}</h2>
              <span>{findings.length}</span>
            </div>
            {findings.length ? (
              <div className="finding-grid">{findings.map(findingCard)}</div>
            ) : (
              <p className="empty-section">
                {section.kind === "blocker"
                  ? "No deterministic hard blockers found."
                  : section.kind === "unknown"
                    ? "No missing-evidence signals in this snapshot."
                    : "None in this snapshot."}
              </p>
            )}
          </section>
        );
      })}
      <section className="report-section" aria-label="Pre-deployment checklist">
        <div className="section-heading">
          <h2>Pre-deployment checklist</h2>
          <span>Suggested actions</span>
        </div>
        <div className="panel checklist">
          {decision.checklist.length ? (
            <ol>
              {decision.checklist.map((item) => (
                <li key={item.id}>
                  <span className="checklist-marker" aria-hidden="true">
                    ○
                  </span>
                  <div>
                    <p>{item.title}</p>
                    <small>
                      {item.required
                        ? "Required follow-up"
                        : "Recommended review"}{" "}
                      · Not verified as completed
                    </small>
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <p>
              No additional actions were triggered by the readiness policy.
              Follow your normal deployment process.
            </p>
          )}
        </div>
      </section>
      <details className="panel technical-details">
        <summary>Technical details & evidence snapshot</summary>
        <dl>
          <dt>Analysis ID</dt>
          <dd>
            <code>{report.id}</code>
          </dd>
          <dt>Created</dt>
          <dd>{report.created_at}</dd>
          <dt>Policy</dt>
          <dd>{decision.policy_version}</dd>
          <dt>Pipeline</dt>
          <dd>
            Captured evidence → Python policy → saved report. See analysis
            activity for the model and tool calls used by background analyses.
          </dd>
        </dl>
        <div className="citations">
          {report.evidence.map((item) => (
            <button
              className="citation-button"
              key={item.id}
              onClick={() => setSelected(item)}
            >
              {item.title}
            </button>
          ))}
        </div>
      </details>
      <EvidenceDrawer
        synthetic={report.source_mode === "demo"}
        evidence={selected}
        onClose={() => setSelected(null)}
      />
    </>
  );
}
