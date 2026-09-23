"use client";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Workspace } from "@/components/workspace";
import { api, type Me } from "@/lib/api";
type Connection = {
  repository: { full_name: string; status: string; auth_mode: string } | null;
  app_configured: boolean;
  install_url: string | null;
  authorized_installations: number[];
};
function Settings({ me }: { me: Me }) {
  const [repo, setRepo] = useState("");
  const [mode, setMode] = useState("public");
  const [installation, setInstallation] = useState("");
  const connection = useQuery({
    queryKey: ["connection", me.workspace_id],
    queryFn: () => api<Connection>("/github/connection"),
  });
  const connect = useMutation({
    mutationFn: () =>
      api("/github/connect", {
        method: "POST",
        headers: { "X-CSRF-Token": me.csrf_token },
        body: JSON.stringify({
          full_name: repo,
          mode,
          installation_id: mode === "app" ? Number(installation) : null,
        }),
      }),
    onSuccess: () => connection.refetch(),
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">WORKSPACE SETTINGS</span>
          <h1>Connect release evidence.</h1>
          <p>
            One repository per workspace keeps collection and access explicit.
          </p>
        </div>
      </div>
      <section className="panel analysis-form">
        <h2>GitHub connection</h2>
        {connection.data?.repository && (
          <p>
            <strong>{connection.data.repository.full_name}</strong> ·{" "}
            {connection.data.repository.status} ·{" "}
            {connection.data.repository.auth_mode}
          </p>
        )}
        {connection.error && <p role="alert">{connection.error.message}</p>}
        {connection.data?.app_configured ? (
          <p>
            {connection.data.install_url && (
              <a
                href={connection.data.install_url}
                target="_blank"
                rel="noreferrer"
              >
                Install GitHub App ↗
              </a>
            )}{" "}
            · <a href="/api/v1/github/authorize">Authorize your installation</a>
          </p>
        ) : (
          <div className="demo-notice">
            Public repositories work without App credentials. For private
            repositories, configure the GitHub App settings described in the
            README.
          </div>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            connect.mutate();
          }}
        >
          <label htmlFor="repository">Repository · owner/name</label>
          <input
            id="repository"
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            placeholder="octocat/Hello-World"
            required
            maxLength={200}
          />
          <label htmlFor="connection-mode">Access</label>
          <select
            id="connection-mode"
            value={mode}
            onChange={(e) => setMode(e.target.value)}
          >
            <option value="public">Public repository</option>
            <option value="app" disabled={!connection.data?.app_configured}>
              GitHub App installation
            </option>
          </select>
          {mode === "app" && (
            <>
              <label htmlFor="installation">Authorized installation</label>
              <select
                id="installation"
                value={installation}
                onChange={(e) => setInstallation(e.target.value)}
                required
              >
                <option value="">Select installation</option>
                {connection.data?.authorized_installations.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
            </>
          )}
          {connect.error && (
            <p role="alert" className="error">
              {connect.error.message}
            </p>
          )}
          <button disabled={connect.isPending}>
            {connect.isPending ? "Connecting…" : "Connect repository"}
          </button>
        </form>
      </section>
    </>
  );
}
export default function SettingsPage() {
  return <Workspace>{(me) => <Settings me={me} />}</Workspace>;
}
