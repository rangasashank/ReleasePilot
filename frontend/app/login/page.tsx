"use client";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { api } from "@/lib/api";

type Credentials = { email: string; password: string };
export default function Login() {
  const router = useRouter();
  const client = useQueryClient();
  const { register, handleSubmit } = useForm<Credentials>();
  const login = useMutation({
    mutationFn: (data: Credentials) =>
      api<void>("/auth/demo/login", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      client.clear();
      router.replace("/dashboard");
    },
  });
  return (
    <main id="main-content" className="login-page">
      <section className="login-intro">
        <div className="brand">
          <span className="brand-mark">R</span>ReleasePilot
        </div>
        <div>
          <span className="eyebrow">YOUR RELEASE WORKSPACE</span>
          <h1>
            Good releases start
            <br />
            with clear evidence.
          </h1>
          <p>
            Bring your services into one workspace. Build toward release
            decisions you can explain.
          </p>
        </div>
        <small>Release readiness, backed by evidence</small>
      </section>
      <section className="login-panel">
        <div className="login-card">
          <span className="phase-pill">LOCAL DEMO</span>
          <h2>Welcome back.</h2>
          <p>Sign in to your ReleasePilot workspace.</p>
          <form onSubmit={handleSubmit((data) => login.mutate(data))}>
            <label htmlFor="email">Email address</label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              placeholder="demo@releasepilot.local"
              required
              {...register("email")}
            />
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              {...register("password")}
            />
            {login.error && (
              <p className="error" role="alert">
                {login.error.message}
              </p>
            )}
            <button disabled={login.isPending} type="submit">
              {login.isPending ? "Signing in…" : "Sign in to workspace"}
              <span aria-hidden="true"> →</span>
            </button>
          </form>
          <p className="login-note">
            Use the demo account configured during local setup.
          </p>
        </div>
      </section>
    </main>
  );
}
