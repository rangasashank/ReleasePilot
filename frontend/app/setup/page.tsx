"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Workspace } from "@/components/workspace";
import { ServiceForm, type ServiceFields } from "@/components/service-form";
import { api, type Me, type Service } from "@/lib/api";

function Setup({ me }: { me: Me }) {
  const router = useRouter();
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: (data: ServiceFields) =>
      api<Service>("/services", {
        method: "POST",
        headers: { "X-CSRF-Token": me.csrf_token },
        body: JSON.stringify(data),
      }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["services"] });
      router.push("/dashboard");
    },
  });
  return (
    <>
      <Link className="back-link" href="/dashboard">
        ← Workspace overview
      </Link>
      <div className="page-heading">
        <div>
          <span className="eyebrow">SERVICE SETUP</span>
          <h1>A place for your next release.</h1>
          <p>
            Start with a name. Connect release evidence as your workspace grows.
          </p>
        </div>
      </div>
      <div className="setup-grid">
        <section className="panel">
          <div className="panel-heading">
            <span className="service-icon">01</span>
            <div>
              <h2>Service details</h2>
              <p>Create a service in {me.workspace_name}.</p>
            </div>
          </div>
          <ServiceForm
            onSubmit={(data) => mutation.mutate(data)}
            pending={mutation.isPending}
            error={mutation.error?.message}
          />
        </section>
        <aside className="setup-aside">
          <h3>What is a service?</h3>
          <p>
            A service is the application you release, such as a checkout API,
            storefront, or background worker.
          </p>
          <hr />
          <h3>Next, you’ll connect</h3>
          <p>
            <strong>GitHub repository</strong>
            <br />
            Code changes, reviews, and CI checks.
          </p>
          <p>
            <strong>Deployment runbook</strong>
            <br />
            The steps and checks your team follows.
          </p>
          <span className="hint">
            Connect GitHub in Connections and add deployment guidance in Runbooks.
          </span>
        </aside>
      </div>
    </>
  );
}
export default function SetupPage() {
  return <Workspace>{(me) => <Setup me={me} />}</Workspace>;
}
