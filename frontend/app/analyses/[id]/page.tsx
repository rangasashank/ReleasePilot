"use client";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Workspace } from "@/components/workspace";
import { ReportView } from "@/components/reports/report-view";
import { api, type AnalysisReport, type Me } from "@/lib/api";

type Status = {
  state: string;
  stage: string;
  stale: boolean;
  error_code: string | null;
  attempts: number;
  retry_at: string | null;
  agents: {
    name: string;
    state: string;
    model: string;
    tokens: number;
    duration_ms: number;
    output: { summary?: string; missing_evidence?: string[] };
  }[];
  tools: { name: string; agent: string; status: string; duration_ms: number }[];
};
function SavedReport({ me }: { me: Me }) {
  const { id } = useParams<{ id: string }>();
  const status = useQuery({
    queryKey: ["analysis-status", me.workspace_id, id],
    queryFn: () => api<Status>(`/analyses/${id}/status`),
    refetchInterval: (q) =>
      ["COMPLETED", "PARTIAL", "FAILED"].includes(q.state.data?.state ?? "")
        ? false
        : 2000,
  });
  const done = ["COMPLETED", "PARTIAL"].includes(status.data?.state ?? "");
  const report = useQuery({
    queryKey: ["analysis", me.workspace_id, id],
    queryFn: () => api<AnalysisReport>(`/analyses/${id}`),
    enabled: done,
  });
  const retry = useMutation({
    mutationFn: () =>
      api(`/analyses/${id}/retry`, {
        method: "POST",
        headers: { "X-CSRF-Token": me.csrf_token },
      }),
    onSuccess: () => status.refetch(),
  });
  return (
    <>
      {status.error && (
        <section className="panel empty">
          <p role="alert">{status.error.message}</p>
          <button onClick={() => status.refetch()}>Try again</button>
        </section>
      )}
      {!done && !status.error && (
        <section className="panel empty" aria-live="polite">
          <span className="eyebrow">RELEASE ANALYSIS</span>
          <h1>
            {status.data?.state === "FAILED"
              ? "Analysis needs attention"
              : status.data?.state === "WAITING"
                ? "Waiting for a dependency"
                : "Reviewing the release…"}
          </h1>
          <p>
            Stage: {status.data?.stage ?? "Loading"} · Attempt{" "}
            {status.data?.attempts ?? 0}
          </p>
          {status.data?.error_code && <p>{status.data.error_code}</p>}
          {status.data?.retry_at && (
            <p>
              Automatic retry after{" "}
              {new Date(status.data.retry_at).toLocaleTimeString()}.
            </p>
          )}
          {status.data?.state === "FAILED" && (
            <button disabled={retry.isPending} onClick={() => retry.mutate()}>
              Retry unfinished work
            </button>
          )}
          {retry.error && <p role="alert">{retry.error.message}</p>}
          <p>
            You can leave this page and return. Work continues in the
            background.
          </p>
          <Link href="/dashboard">Back to overview</Link>
        </section>
      )}
      {status.data?.stale && (
        <div className="demo-notice">
          New GitHub activity may affect this release. This report preserves its
          original evidence.{" "}
          <Link href="/analyses/new">Run a new analysis</Link>.
        </div>
      )}
      {status.data?.state === "PARTIAL" && (
        <div className="demo-notice">
          Specialist review was incomplete. Inspect the activity details and
          missing evidence before deciding.
        </div>
      )}
      {report.data && <ReportView report={report.data} />}
      {report.error && <p role="alert">{report.error.message}</p>}
      {!!status.data?.agents.length && (
        <details className="panel activity">
          <summary>Analysis activity · agents and MCP tools</summary>
          {status.data.agents.map((a, i) => (
            <article key={`${a.name}:${i}`}>
              <h3>
                {a.name} · {a.state}
              </h3>
              <p>
                {a.model} · {a.tokens} tokens ·{" "}
                {(a.duration_ms / 1000).toFixed(1)}s
              </p>
              <p>{a.output.summary}</p>
              {a.output.missing_evidence?.map((m) => (
                <p key={m}>{m}</p>
              ))}
            </article>
          ))}
          <ul>
            {status.data.tools.map((t, i) => (
              <li key={i}>
                {t.agent}: {t.name} · {t.status} · {t.duration_ms}ms
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
export default function AnalysisPage() {
  return <Workspace>{(me) => <SavedReport me={me} />}</Workspace>;
}
