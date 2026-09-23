"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Workspace } from "@/components/workspace";
import { api, type Me, type Service } from "@/lib/api";
type Document = {
  id: string;
  title: string;
  status: string;
  error_code: string | null;
  embedding_model: string;
};
type Chunk = {
  chunk_id: string;
  title: string;
  heading: string;
  page: number | null;
  excerpt: string;
};
function Knowledge({ me }: { me: Me }) {
  const [service, setService] = useState("");
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const client = useQueryClient();
  const services = useQuery({
    queryKey: ["services", me.workspace_id],
    queryFn: () => api<Service[]>("/services?limit=100"),
  });
  const selected = service || services.data?.[0]?.id || "";
  const docs = useQuery({
    queryKey: ["documents", me.workspace_id, selected],
    queryFn: () => api<Document[]>(`/documents?service_id=${selected}`),
    enabled: !!selected,
    refetchInterval: (q) =>
      q.state.data?.some((d) => d.status === "QUEUED") ? 2000 : false,
  });
  const results = useQuery({
    queryKey: ["search", me.workspace_id, selected, submitted],
    queryFn: () =>
      api<Chunk[]>(
        `/documents/search?service_id=${selected}&query=${encodeURIComponent(submitted)}`,
      ),
    enabled: !!selected && !!submitted,
  });
  const mutation = useMutation({
    mutationFn: async () => {
      const body = new FormData();
      body.set("service_id", selected);
      body.set("file", file!);
      return api("/documents", {
        method: "POST",
        headers: { "X-CSRF-Token": me.csrf_token },
        body,
      });
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["documents"] }),
  });
  const action = useMutation({
    mutationFn: ({ id, reindex }: { id: string; reindex: boolean }) =>
      api(`/documents/${id}${reindex ? "/reindex" : ""}`, {
        method: reindex ? "POST" : "DELETE",
        headers: { "X-CSRF-Token": me.csrf_token },
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["documents"] }),
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">DEPLOYMENT KNOWLEDGE</span>
          <h1>Put your runbooks to work.</h1>
          <p>
            Upload deployment and rollback guidance. Reports cite the exact
            retrieved passages.
          </p>
        </div>
      </div>
      <section className="panel analysis-form">
        <label htmlFor="knowledge-service">Service</label>
        <select
          id="knowledge-service"
          value={selected}
          onChange={(e) => {
            setService(e.target.value);
            setSubmitted("");
          }}
        >
          {services.data?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        {!selected && <p>Create a service in Service setup first.</p>}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate();
          }}
        >
          <label htmlFor="runbook">
            Runbook · Markdown, text, or PDF · up to 5 MB
          </label>
          <input
            id="runbook"
            type="file"
            accept=".md,.txt,.pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            required
          />
          <button disabled={!selected || !file || mutation.isPending}>
            {mutation.isPending ? "Uploading…" : "Upload and index"}
          </button>
        </form>
        {mutation.error && <p role="alert">{mutation.error.message}</p>}
        {action.error && <p role="alert">{action.error.message}</p>}
        <div className="knowledge-list">
          {docs.data?.map((d) => (
            <article key={d.id}>
              <h3>{d.title}</h3>
              <p>
                {d.status} ·{" "}
                {d.embedding_model === "demo-hash-v1"
                  ? "Demo text vectors · no model API"
                  : d.embedding_model}
              </p>
              {d.error_code && <p>{d.error_code}</p>}
              <button
                className="secondary"
                disabled={action.isPending || d.status === "QUEUED"}
                onClick={() => action.mutate({ id: d.id, reindex: true })}
              >
                Reindex
              </button>{" "}
              <button
                className="secondary"
                disabled={action.isPending}
                onClick={() => action.mutate({ id: d.id, reindex: false })}
              >
                Remove
              </button>
            </article>
          ))}
        </div>
        {docs.data?.length === 0 && (
          <p>No runbooks yet. Add deployment steps or a rollback procedure.</p>
        )}
      </section>
      <section className="panel analysis-form">
        <h2>Inspect retrieval</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setSubmitted(query);
          }}
        >
          <label htmlFor="search">What guidance do you need?</label>
          <input
            id="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            maxLength={2000}
            placeholder="How do we roll back a database migration?"
            required
          />
          <button disabled={!selected}>Search passages</button>
        </form>
        {results.isFetching && <p role="status">Searching…</p>}
        {results.error && <p role="alert">{results.error.message}</p>}
        {results.data?.length === 0 && (
          <p>No relevant indexed passages found.</p>
        )}
        {results.data?.map((c) => (
          <article className="retrieval-result" key={c.chunk_id}>
            <h3>
              {c.title} · {c.heading}
              {c.page ? ` · page ${c.page}` : ""}
            </h3>
            <p>{c.excerpt}</p>
          </article>
        ))}
      </section>
    </>
  );
}
export default function KnowledgePage() {
  return <Workspace>{(me) => <Knowledge me={me} />}</Workspace>;
}
