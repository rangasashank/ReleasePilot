"use client";
import { Suspense, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Workspace } from "@/components/workspace";
import { api, type Me, type Scenario, type Service } from "@/lib/api";

function NewAnalysis({ me }: { me: Me }) {
  const params = useSearchParams();
  const [service, setService] = useState(params.get("service") ?? "");
  const [mode, setMode] = useState("demo");
  const [scenario, setScenario] = useState("failed_ci");
  const [base, setBase] = useState("");
  const [head, setHead] = useState("");
  const request = useRef<{ input: string; key: string } | null>(null);
  const router = useRouter();
  const services = useQuery({
    queryKey: ["services", me.workspace_id],
    queryFn: () => api<Service[]>("/services?limit=100"),
  });
  const scenarios = useQuery({
    queryKey: ["scenarios"],
    queryFn: () => api<Scenario[]>("/demo/scenarios"),
  });
  const refs = useQuery({
    queryKey: ["refs", me.workspace_id],
    queryFn: () =>
      api<{ refs: { name: string; sha: string; kind: string }[] }>(
        "/github/refs",
      ),
    enabled: mode === "github",
    retry: false,
  });
  const selected = service || services.data?.[0]?.id || "";
  const mutation = useMutation({
    mutationFn: () => {
      const input = JSON.stringify({
        service_id: selected,
        mode,
        scenario,
        base_ref: base,
        head_ref: head,
      });
      if (request.current?.input !== input)
        request.current = { input, key: crypto.randomUUID() };
      return api<{ id: string }>("/analyses", {
        method: "POST",
        headers: {
          "X-CSRF-Token": me.csrf_token,
          "Idempotency-Key": request.current.key,
        },
        body: input,
      });
    },
    onSuccess: (report) => router.push(`/analyses/${report.id}`),
  });
  return (
    <>
      <Link className="back-link" href="/dashboard">
        ← Workspace overview
      </Link>
      <div className="page-heading">
        <div>
          <span className="eyebrow">RELEASE READINESS</span>
          <h1>Make the next release an informed decision.</h1>
          <p>
            Capture evidence, review deployment guidance, and inspect a
            traceable recommendation.
          </p>
        </div>
      </div>
      {services.error && <p role="alert">{services.error.message}</p>}
      {!services.isPending && !services.data?.length ? (
        <section className="panel empty">
          <h2>Create a service first</h2>
          <Link href="/setup">Set up your service →</Link>
        </section>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate();
          }}
          className="panel analysis-form"
        >
          <label htmlFor="service">Service</label>
          <select
            id="service"
            value={selected}
            onChange={(e) => setService(e.target.value)}
            required
          >
            {services.data?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <label htmlFor="mode">Evidence source</label>
          <select
            id="mode"
            value={mode}
            onChange={(e) => setMode(e.target.value)}
          >
            <option value="demo">Demo fixtures · no credentials needed</option>
            <option value="github">Connected GitHub repository</option>
          </select>
          {mode === "demo" ? (
            <>
              <div className="demo-notice">
                Synthetic evidence and deterministic agents exercise the
                background workflow. No language model is called.
              </div>
              <fieldset>
                <legend>Evidence scenario</legend>
                <div className="scenario-grid">
                  {scenarios.data?.map((s) => (
                    <label
                      key={s.id}
                      className={`scenario-card ${scenario === s.id ? "selected" : ""}`}
                    >
                      <input
                        type="radio"
                        name="scenario"
                        checked={scenario === s.id}
                        onChange={() => setScenario(s.id)}
                      />
                      <strong>{s.title}</strong>
                      <span>{s.description}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
            </>
          ) : (
            <>
              {refs.error && (
                <p role="alert">
                  {refs.error.message}{" "}
                  <Link href="/settings">Connect GitHub</Link>
                </p>
              )}
              <p>
                Select a branch, tag, or full commit SHA. References are
                resolved and frozen when submitted.
              </p>
              <datalist id="release-refs">
                {refs.data?.refs.map((r) => (
                  <option key={`${r.kind}:${r.name}`} value={r.name}>
                    {r.kind} · {r.sha.slice(0, 8)}
                  </option>
                ))}
              </datalist>
              <label htmlFor="base">Base reference</label>
              <input
                id="base"
                list="release-refs"
                value={base}
                onChange={(e) => setBase(e.target.value)}
                maxLength={200}
                required
              />
              <label htmlFor="head">Target reference</label>
              <input
                id="head"
                list="release-refs"
                value={head}
                onChange={(e) => setHead(e.target.value)}
                maxLength={200}
                required
              />
            </>
          )}
          {mutation.error && (
            <p className="error" role="alert">
              {mutation.error.message}
            </p>
          )}
          <div className="form-footer">
            <span>Evidence and results are saved in your workspace.</span>
            <button disabled={mutation.isPending || !selected}>
              {mutation.isPending ? "Submitting…" : "Start analysis →"}
            </button>
          </div>
        </form>
      )}
    </>
  );
}
export default function NewAnalysisPage() {
  return (
    <Suspense fallback={<p role="status">Loading…</p>}>
      <Workspace>{(me) => <NewAnalysis me={me} />}</Workspace>
    </Suspense>
  );
}
