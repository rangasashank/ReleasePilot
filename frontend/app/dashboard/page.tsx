"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { RecentAnalyses } from "@/components/reports/recent-analyses";
import { Workspace } from "@/components/workspace";
import { api, type Service } from "@/lib/api";

function Overview({ workspaceId }: { workspaceId: string }) {
  const [page, setPage] = useState(0);
  const services = useQuery({
    queryKey: ["services", workspaceId, page],
    queryFn: () => api<Service[]>(`/services?limit=20&offset=${page * 20}`),
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">RELEASE READINESS</span>
          <h1>Workspace overview</h1>
          <p>A home for your services and their next release.</p>
        </div>
        <Link className="button" href="/setup">
          + Add service
        </Link>
      </div>
      <section className="foundation-banner">
        <div className="banner-icon" aria-hidden="true">
          ↗
        </div>
        <div>
          <span className="phase-pill">EXPLORE THE POLICY ENGINE</span>
          <h2>See what makes a release ready.</h2>
          <p>
            Try safe, failed-CI, and missing-evidence fixtures. Every
            recommendation comes with its evidence.
          </p>
        </div>
        <span className="banner-number" aria-hidden="true">
          02
        </span>
      </section>
      <RecentAnalyses workspaceId={workspaceId} />
      <div className="section-heading">
        <h2>Your services</h2>
        <span>Workspace services</span>
      </div>
      {services.isPending ? (
        <div className="panel empty" role="status">
          Loading services…
        </div>
      ) : services.error ? (
        <div className="panel empty">
          <p className="error" role="alert">
            {services.error.message}
          </p>
          <button onClick={() => services.refetch()}>Try again</button>
        </div>
      ) : services.data?.length ? (
        <div className="service-grid">
          {services.data.map((service) => (
            <article className="panel service-card" key={service.id}>
              <div className="service-card-top">
                <span className="service-icon" aria-hidden="true">
                  {service.name.charAt(0).toUpperCase()}
                </span>
                <span className="status-pill">Service active</span>
              </div>
              <h3>{service.name}</h3>
              <p>{service.description || "No description added."}</p>
              <div className="service-card-bottom">
                <span>Release workspace</span>
                <Link href={`/analyses/new?service=${service.id}`}>
                  Analyze release →
                </Link>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="panel empty">
          <div className="empty-icon" aria-hidden="true">
            ▤
          </div>
          <h3>No services yet</h3>
          <p>Add your first service to get your workspace ready.</p>
          <Link href="/setup" className="button">
            Create your first service →
          </Link>
        </div>
      )}
      {(page > 0 || services.data?.length === 20) && (
        <div className="pagination">
          <button disabled={page === 0} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <span>Page {page + 1}</span>
          <button
            disabled={services.data?.length !== 20}
            onClick={() => setPage(page + 1)}
          >
            Next
          </button>
        </div>
      )}
      <section className="next-steps">
        <div>
          <span className="step-number">01</span>
          <h3>Create a service</h3>
          <p>Give your application a name and a place in your workspace.</p>
          <span className="step-current">Available now</span>
        </div>
        <div>
          <span className="step-number">02</span>
          <h3>Connect your evidence</h3>
          <p>Bring in GitHub changes, checks, and deployment runbooks.</p>
          <Link href="/settings">Connect GitHub →</Link>
        </div>
        <div>
          <span className="step-number">03</span>
          <h3>Review a release</h3>
          <p>Understand risks with clear recommendations and citations.</p>
          <span className="step-current">Available now</span>
        </div>
      </section>
    </>
  );
}
export default function Dashboard() {
  return (
    <Workspace>{(me) => <Overview workspaceId={me.workspace_id} />}</Workspace>
  );
}
