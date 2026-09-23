"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { api, ApiError, type Me } from "@/lib/api";

export function Workspace({
  children,
}: {
  children: (me: Me) => React.ReactNode;
}) {
  const router = useRouter();
  const path = usePathname();
  const client = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/me") });
  const logout = useMutation({
    mutationFn: () =>
      api<void>("/auth/logout", {
        method: "POST",
        headers: { "X-CSRF-Token": me.data?.csrf_token ?? "" },
      }),
    onSuccess: () => {
      client.clear();
      router.replace("/login");
    },
  });
  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401)
      router.replace("/login");
  }, [me.error, router]);
  if (me.isPending)
    return (
      <main className="loading" role="status">
        Opening your workspace…
      </main>
    );
  if (!me.data)
    return (
      <main className="loading">
        <p role="alert">{me.error?.message}</p>
        <button onClick={() => me.refetch()}>Try again</button>
        <Link href="/login">Sign in</Link>
      </main>
    );
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link href="/dashboard" className="brand">
          <span className="brand-mark">R</span>ReleasePilot
        </Link>
        <div className="workspace-label">
          <span className="workspace-avatar">D</span>
          <div>
            {me.data.workspace_name}
            <small>Local demo</small>
          </div>
        </div>
        <p className="nav-label">WORKSPACE</p>
        <nav aria-label="Main navigation">
          <Link
            aria-current={path === "/dashboard" ? "page" : undefined}
            href="/dashboard"
          >
            <span aria-hidden="true">▦</span> Overview
          </Link>
          <Link
            aria-current={path === "/setup" ? "page" : undefined}
            href="/setup"
          >
            <span aria-hidden="true">⊕</span> Service setup
          </Link>
          <Link
            aria-current={path.startsWith("/analyses") ? "page" : undefined}
            href="/analyses/new"
          >
            <span aria-hidden="true">▤</span> Release analysis
          </Link>
          <Link
            aria-current={path === "/knowledge" ? "page" : undefined}
            href="/knowledge"
          >
            <span aria-hidden="true">▧</span> Runbooks
          </Link>
          <Link
            aria-current={path === "/settings" ? "page" : undefined}
            href="/settings"
          >
            <span aria-hidden="true">⚙</span> Connections
          </Link>
        </nav>
        <div className="sidebar-bottom">
          <span className="phase-pill">READINESS WORKSPACE</span>
          <p>Evidence-backed decisions, step by step.</p>
          <div className="profile">
            <span className="workspace-avatar">DD</span>
            <div>
              {me.data.name}
              <small>{me.data.email}</small>
            </div>
          </div>
          <button
            className="text-button"
            disabled={logout.isPending}
            onClick={() => logout.mutate()}
          >
            Sign out
          </button>
          {logout.error && (
            <p role="alert" className="error">
              {logout.error.message}
            </p>
          )}
        </div>
      </aside>
      <div className="main-column">
        <header className="topbar">
          <span>
            Workspace <span className="slash">/</span>{" "}
            {path === "/setup"
              ? "Service setup"
              : path.startsWith("/analyses")
                ? "Release analysis"
                : path === "/knowledge"
                  ? "Runbooks"
                  : path === "/settings"
                    ? "Connections"
                    : "Overview"}
          </span>
          <span className="demo-label">RELEASEPILOT</span>
        </header>
        <main id="main-content" className="content">
          {children(me.data)}
        </main>
      </div>
    </div>
  );
}
