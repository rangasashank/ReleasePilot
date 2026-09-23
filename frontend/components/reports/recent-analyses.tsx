"use client";
import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, type AnalysisSummary } from "@/lib/api";
import { RecommendationBadge } from "./report-view";

export function RecentAnalyses({ workspaceId }: { workspaceId: string }) {
  const [page, setPage] = useState(0);
  const reports = useQuery({
    queryKey: ["analyses", workspaceId, page],
    queryFn: () =>
      api<AnalysisSummary[]>(`/analyses?limit=10&offset=${page * 10}`),
    refetchInterval: (q) =>
      q.state.data?.some(
        (r) => !["COMPLETED", "PARTIAL", "FAILED"].includes(r.state),
      )
        ? 3000
        : false,
  });
  return (
    <section className="report-section">
      <div className="section-heading">
        <h2>Recent analyses</h2>
        <Link href="/analyses/new" className="back-link">
          New analysis →
        </Link>
      </div>
      {reports.isPending ? (
        <p role="status">Loading reports…</p>
      ) : reports.error ? (
        <div className="panel empty">
          <p role="alert">{reports.error.message}</p>
          <button onClick={() => reports.refetch()}>Try again</button>
        </div>
      ) : reports.data?.length ? (
        <div className="panel recent-reports">
          {reports.data.map((report) => (
            <Link
              className="recent-report"
              href={`/analyses/${report.id}`}
              key={report.id}
            >
              <div>
                <strong>{report.service_name}</strong>
                <small>
                  {report.source_mode.toUpperCase()} ·{" "}
                  {report.scenario.replaceAll("_", " ")} ·{" "}
                  {report.head_sha.slice(0, 7)}
                </small>
              </div>
              <div className="recent-metrics">
                {["COMPLETED", "PARTIAL"].includes(report.state) ? (
                  <>
                    <span>
                      Risk {report.risk_score} · Confidence{" "}
                      {report.confidence_score}
                    </span>
                    <RecommendationBadge value={report.recommendation} />
                  </>
                ) : (
                  <span className="status-pill">{report.state}</span>
                )}
                <span aria-hidden="true">→</span>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="panel empty">
          <h3>No analyses yet</h3>
          <p>Try a fixture to see how evidence becomes a readiness decision.</p>
          <Link className="button" href="/analyses/new">
            Explore the scenarios →
          </Link>
        </div>
      )}
      {(page > 0 || reports.data?.length === 10) && (
        <div className="pagination">
          <button disabled={page === 0} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <span>Page {page + 1}</span>
          <button
            disabled={reports.data?.length !== 10}
            onClick={() => setPage(page + 1)}
          >
            Next
          </button>
        </div>
      )}
    </section>
  );
}
