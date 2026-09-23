import type { components } from "./generated/api";

export type Me = components["schemas"]["MeOutput"];
export type Service = components["schemas"]["ServiceOutput"];
export type SetupStatus = components["schemas"]["SetupOutput"];
export type AnalysisReport = components["schemas"]["AnalysisReport"];
export type AnalysisSummary = components["schemas"]["AnalysisSummary"];
export type Scenario = components["schemas"]["ScenarioOutput"];
export type Finding = components["schemas"]["Finding"];
export type Evidence = components["schemas"]["Evidence"];

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public requestId?: string,
  ) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    credentials: "same-origin",
    headers: {
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...options.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(
      response.status,
      body.message ?? "Unable to reach ReleasePilot. Try again.",
      body.request_id,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
