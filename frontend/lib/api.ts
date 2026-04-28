"use client";

export type Role = "admin" | "analyst" | "reviewer" | "reader";

export type Network = {
  key: string;
  name: string;
  network_type: string;
  chain_id: number;
  supports_trace_transaction: boolean;
  supports_debug_trace_transaction: boolean;
  supports_historical_eth_call: boolean;
};

export type CaseRecord = {
  id: string;
  title: string | null;
  network_key: string;
  seed_type: string;
  seed_value: string;
  time_window_hours: number;
  depth: string;
  status: string;
  severity: string;
  attack_type: string | null;
  root_cause_one_liner: string | null;
  loss_usd: number | null;
  confidence: string;
  language: string;
  created_at: string;
  updated_at: string;
};

export type CaseSummary = {
  total_cases: number;
  by_status: Record<string, number>;
  by_severity: Record<string, number>;
  review_queue: number;
  high_severity: number;
};

export type CaseDetailSummary = {
  transaction_count: number;
  evidence_count: number;
  finding_count: number;
  report_count: number;
  diagram_count: number;
  job_count: number;
};

export type Transaction = {
  id: string;
  tx_hash: string;
  block_number: number | null;
  block_timestamp: string | null;
  from_address: string | null;
  to_address: string | null;
  method_selector: string | null;
  method_name: string | null;
  phase: string;
  artifact_status: string;
};

export type TimelineItem = {
  tx_id: string;
  tx_hash: string;
  timestamp: string | null;
  block_number: number | null;
  phase: string;
  from_address: string | null;
  to_address: string | null;
  method: string | null;
  confidence: string;
  evidence_count: number;
};

export type Evidence = {
  id: string;
  source_type: string;
  producer: string;
  claim_key: string;
  raw_path: string | null;
  decoded: Record<string, unknown>;
  confidence: string;
  created_at: string;
};

export type Finding = {
  id: string;
  title: string;
  finding_type: string;
  severity: string;
  confidence: string;
  claim: string;
  rationale: string | null;
  falsification: string | null;
  evidence_ids: string[];
  reviewer_status: string;
  reviewer_comment: string | null;
};

export type Report = {
  id: string;
  version: number;
  language: string;
  format: string;
  status: string;
  object_path: string | null;
  content_hash: string | null;
  evidence_coverage: Record<string, unknown>;
  content?: string | Record<string, unknown> | null;
};

export type ReportExport = {
  id: string;
  report_id: string;
  format: string;
  status: string;
  object_path: string | null;
  content_hash: string | null;
  error: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type DiagramSpec = {
  id: string;
  case_id: string;
  report_id: string | null;
  diagram_type: string;
  title: string;
  mermaid_source: string;
  nodes_edges?: Record<string, unknown>;
  evidence_ids: string[];
  confidence: string;
  source_type: string;
  object_path: string | null;
};

export type JobRun = {
  id: string;
  job_name: string;
  status: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  error: string | null;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
};

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8100/api";

export async function apiFetch<T>(path: string, init: RequestInit = {}, role: Role = "admin"): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("x-user-id", "local-ui");
  headers.set("x-user-role", role);
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json() as Promise<T>;
}
