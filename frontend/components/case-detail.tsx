"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, FileText, Play, RefreshCw, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { API_BASE, apiFetch, CaseDetailSummary, CaseRecord, DiagramSpec, Evidence, Finding, JobRun, Report, ReportExport, Role, TimelineItem, WorkflowRun } from "@/lib/api";
import { JsonInspector } from "@/components/json-inspector";
import { ReportPreview } from "@/components/report-preview";
import { Shell, ShellCaseTab } from "@/components/shell";
import { StatusBadge } from "@/components/status-badge";

export type CaseTab = "overview" | "diagrams" | "evidence" | "findings" | "reports" | "jobs";
type ShellTab = Extract<CaseTab, ShellCaseTab>;
const caseTabs: CaseTab[] = ["overview", "diagrams", "evidence", "findings", "reports", "jobs"];
const PAGE_SIZE = 50;
const REPORT_PAGE_SIZE = 20;
const tabLabels: Record<CaseTab, string> = {
  overview: "Overview",
  diagrams: "Diagrams",
  evidence: "Evidence",
  findings: "Findings",
  reports: "Reports",
  jobs: "Jobs"
};

export function CaseDetail({ caseId, initialTab = "overview" }: { caseId: string; initialTab?: CaseTab }) {
  const [role, setRole] = useState<Role>("admin");
  const [tab, setTab] = useState<CaseTab>(initialTab);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [timelineOffset, setTimelineOffset] = useState(0);
  const [evidenceOffset, setEvidenceOffset] = useState(0);
  const [findingsOffset, setFindingsOffset] = useState(0);
  const [reportsOffset, setReportsOffset] = useState(0);
  const [jobsOffset, setJobsOffset] = useState(0);
  const queryClient = useQueryClient();
  const showDiagrams = tab === "diagrams";
  const showEvidence = tab === "evidence";
  const showFindings = tab === "findings";
  const showReports = tab === "reports";
  const showJobs = tab === "jobs";
  const caseQuery = useQuery({ queryKey: ["case", caseId, role], queryFn: () => apiFetch<CaseRecord>(`/cases/${caseId}`, {}, role) });
  const detailSummary = useQuery({ queryKey: ["case-summary", caseId, role], queryFn: () => apiFetch<CaseDetailSummary>(`/cases/${caseId}/summary`, {}, role) });
  const timeline = useQuery({
    queryKey: ["timeline", caseId, role, timelineOffset],
    enabled: showDiagrams,
    queryFn: () => apiFetch<TimelineItem[]>(`/cases/${caseId}/timeline?limit=${PAGE_SIZE}&offset=${timelineOffset}`, {}, role)
  });
  const diagrams = useQuery({
    queryKey: ["diagrams", caseId, role],
    enabled: showDiagrams,
    queryFn: () => apiFetch<DiagramSpec[]>(`/cases/${caseId}/diagrams`, {}, role)
  });
  const evidence = useQuery({
    queryKey: ["evidence", caseId, role, evidenceOffset],
    enabled: showEvidence,
    queryFn: () => apiFetch<Evidence[]>(`/cases/${caseId}/evidence?limit=${PAGE_SIZE}&offset=${evidenceOffset}`, {}, role)
  });
  const findings = useQuery({
    queryKey: ["findings", caseId, role, findingsOffset],
    enabled: showFindings,
    queryFn: () => apiFetch<Finding[]>(`/cases/${caseId}/findings?limit=${PAGE_SIZE}&offset=${findingsOffset}`, {}, role)
  });
  const reports = useQuery({
    queryKey: ["reports", caseId, role, reportsOffset],
    enabled: showReports,
    queryFn: () => apiFetch<Report[]>(`/cases/${caseId}/reports?limit=${REPORT_PAGE_SIZE}&offset=${reportsOffset}`, {}, role)
  });
  const jobs = useQuery({
    queryKey: ["jobs", caseId, role, jobsOffset],
    enabled: showJobs,
    queryFn: () => apiFetch<JobRun[]>(`/cases/${caseId}/jobs?limit=${PAGE_SIZE}&offset=${jobsOffset}`, {}, role)
  });
  const workflowRuns = useQuery({
    queryKey: ["workflow-runs", caseId, role, jobsOffset],
    enabled: showJobs,
    queryFn: () => apiFetch<WorkflowRun[]>(`/cases/${caseId}/workflow-runs?limit=${PAGE_SIZE}&offset=${jobsOffset}`, {}, role)
  });
  const runCase = useMutation({
    mutationFn: () => apiFetch(`/cases/${caseId}/run`, { method: "POST" }, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["case", caseId, role] });
      queryClient.invalidateQueries({ queryKey: ["case-summary", caseId, role] });
      refreshCurrentTab();
    }
  });
  const createReport = useMutation({
    mutationFn: () => apiFetch<Report>(`/cases/${caseId}/reports`, { method: "POST", body: JSON.stringify({ format: "markdown" }) }, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["case", caseId, role] });
      queryClient.invalidateQueries({ queryKey: ["case-summary", caseId, role] });
      queryClient.invalidateQueries({ queryKey: ["reports", caseId, role] });
      if (showReports) {
        refreshCurrentTab();
      }
    }
  });
  const reviewFinding = useMutation({
    mutationFn: ({ findingId, status }: { findingId: string; status: string }) =>
      apiFetch(`/findings/${findingId}/review`, { method: "PATCH", body: JSON.stringify({ reviewer_status: status }) }, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["case-summary", caseId, role] });
      queryClient.invalidateQueries({ queryKey: ["findings", caseId, role] });
    }
  });
  const latestReport = reports.data?.[0];
  const reportDetail = useQuery({
    queryKey: ["report", caseId, latestReport?.id, role],
    enabled: showReports && Boolean(latestReport),
    queryFn: () => apiFetch<Report>(`/cases/${caseId}/reports/${latestReport?.id}`, {}, role)
  });
  const reportExports = useQuery({
    queryKey: ["report-exports", latestReport?.id, role],
    enabled: showReports && Boolean(latestReport),
    queryFn: () => apiFetch<ReportExport[]>(`/reports/${latestReport?.id}/exports`, {}, role),
    refetchInterval: (query) => {
      const rows = query.state.data as ReportExport[] | undefined;
      return rows?.some((item) => item.status === "pending" || item.status === "running") ? 2000 : false;
    }
  });
  const createPdf = useMutation({
    mutationFn: () => apiFetch<ReportExport>(`/reports/${latestReport?.id}/exports`, { method: "POST", body: JSON.stringify({ format: "pdf" }) }, role),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["report-exports", latestReport?.id, role] })
  });
  const selectedEvidence = useMemo(() => evidence.data?.[0], [evidence.data]);
  const canReview = role === "admin" || role === "reviewer";
  const canRun = role === "admin" || role === "analyst";
  const runLabel = itemRunLabel(caseQuery.data?.status);

  async function refreshCurrentTab() {
    setRefreshing(true);
    try {
      const refreshes: Promise<unknown>[] = [caseQuery.refetch(), detailSummary.refetch()];
      if (showDiagrams) {
        refreshes.push(timeline.refetch(), diagrams.refetch());
      }
      if (showEvidence) {
        refreshes.push(evidence.refetch());
      }
      if (showFindings) {
        refreshes.push(findings.refetch());
      }
      if (showReports) {
        refreshes.push(reports.refetch());
        if (latestReport) {
          refreshes.push(reportDetail.refetch(), reportExports.refetch());
        }
      }
      if (showJobs) {
        refreshes.push(jobs.refetch(), workflowRuns.refetch());
      }
      await Promise.all(refreshes);
    } finally {
      setRefreshing(false);
    }
  }

  async function downloadExport(exportId: string) {
    setDownloadError(null);
    const response = await fetch(`${API_BASE}/report-exports/${exportId}/download`, {
      headers: {
        "x-user-id": "local-ui",
        "x-user-role": role
      }
    });
    if (!response.ok) {
      setDownloadError(await response.text());
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `rca-report-${latestReport?.version ?? "latest"}.pdf`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const selectTab = useCallback(
    (value: CaseTab) => {
      setTab(value);
      const query = value === "overview" ? "" : `?tab=${value}`;
      window.history.replaceState(null, "", `/cases/${caseId}${query}`);
    },
    [caseId]
  );

  const item = caseQuery.data;

  return (
    <Shell role={role} onRoleChange={setRole} activeCaseTab={tab === "evidence" ? "overview" : (tab as ShellTab)} onCaseTabChange={selectTab}>
      <div className="content">
        <div className="band">
          <div className="band-header">
            <div>
              <Link href="/">← Dashboard</Link>
              <div className="band-title">{item?.title || caseId}</div>
              <div className="mono">{caseId}</div>
            </div>
            <div className="button-row">
              <button className="btn" disabled={refreshing} onClick={() => refreshCurrentTab()}>
                <RefreshCw size={16} /> {refreshing ? "Refreshing" : "Refresh"}
              </button>
              <button className="btn primary" disabled={!canRun || runCase.isPending} title="Run the full worker pipeline for this case" onClick={() => runCase.mutate()}>
                <Play size={16} /> {runCase.isPending ? "Running" : runLabel}
              </button>
              <button className="btn" disabled={!canRun || createReport.isPending} onClick={() => createReport.mutate()}>
                <FileText size={16} /> Draft Report
              </button>
            </div>
          </div>
          <div className="band-body grid-3">
            <div className="metric">
              <div className="metric-label">Status</div>
              <StatusBadge value={item?.status} />
            </div>
            <div className="metric">
              <div className="metric-label">Severity</div>
              <StatusBadge value={item?.severity} />
            </div>
            <div className="metric">
              <div className="metric-label">Confidence</div>
              <StatusBadge value={item?.confidence} />
            </div>
          </div>
          <div className="tabs">
            {caseTabs.map((value) => (
              <button key={value} className={`tab ${tab === value ? "active" : ""}`} onClick={() => selectTab(value)}>
                {tabLabels[value]}
              </button>
            ))}
          </div>
          <div className="band-body">
            {tab === "overview" ? (
              <Overview item={item} summary={detailSummary.data} />
            ) : null}
            {tab === "diagrams" ? (
              <DiagramsPanel
                diagrams={diagrams.data ?? []}
                timeline={timeline.data ?? []}
                loading={diagrams.isLoading || timeline.isLoading}
                timelineOffset={timelineOffset}
                timelineTotal={detailSummary.data?.transaction_count ?? 0}
                onTimelinePage={setTimelineOffset}
              />
            ) : null}
            {tab === "evidence" ? (
              <EvidencePanel
                evidence={evidence.data ?? []}
                selected={selectedEvidence}
                loading={evidence.isLoading}
                offset={evidenceOffset}
                total={detailSummary.data?.evidence_count ?? 0}
                onPage={setEvidenceOffset}
              />
            ) : null}
            {tab === "findings" ? (
              <FindingsPanel
                findings={findings.data ?? []}
                loading={findings.isLoading}
                canReview={canReview}
                onReview={(findingId, status) => reviewFinding.mutate({ findingId, status })}
                offset={findingsOffset}
                total={detailSummary.data?.finding_count ?? 0}
                onPage={setFindingsOffset}
              />
            ) : null}
            {tab === "reports" ? (
              <ReportsPanel
                reports={reports.data ?? []}
                detail={reportDetail.data}
                exports={reportExports.data ?? []}
                loading={reports.isLoading || reportDetail.isLoading}
                exportError={downloadError || createPdf.error?.message || null}
                onCreatePdf={() => createPdf.mutate()}
                onDownload={downloadExport}
                pdfPending={createPdf.isPending || Boolean(reportExports.data?.some((item) => item.status === "pending" || item.status === "running"))}
                offset={reportsOffset}
                total={detailSummary.data?.report_count ?? 0}
                onPage={setReportsOffset}
              />
            ) : null}
            {tab === "jobs" ? (
              <JobsPanel
                jobs={jobs.data ?? []}
                workflowRuns={workflowRuns.data ?? []}
                loading={jobs.isLoading || workflowRuns.isLoading}
                offset={jobsOffset}
                total={detailSummary.data?.job_count ?? 0}
                onPage={setJobsOffset}
              />
            ) : null}
          </div>
        </div>
      </div>
    </Shell>
  );
}

function itemRunLabel(status?: string) {
  if (!status || status === "CREATED" || status === "FAILED" || status === "CANCELLED") {
    return "Run Analysis";
  }
  return "Re-run Analysis";
}

function Overview({ item, summary }: { item?: CaseRecord; summary?: CaseDetailSummary }) {
  return (
    <div className="grid-2">
      <div className="form-grid">
        <div className="metric">
          <div className="metric-label">Seed</div>
          <div className="mono">
            {item?.seed_type}: {item?.seed_value}
          </div>
        </div>
        <div className="metric">
          <div className="metric-label">Root Cause</div>
          <div>{item?.root_cause_one_liner || "pending"}</div>
        </div>
      </div>
      <div className="grid-3">
        <div className="metric">
          <div className="metric-label">Transactions</div>
          <div className="metric-value">{summary?.transaction_count ?? "-"}</div>
        </div>
        <div className="metric">
          <div className="metric-label">Evidence</div>
          <div className="metric-value">{summary?.evidence_count ?? "-"}</div>
        </div>
        <div className="metric">
          <div className="metric-label">Findings</div>
          <div className="metric-value">{summary?.finding_count ?? "-"}</div>
        </div>
        <div className="metric">
          <div className="metric-label">Jobs</div>
          <div className="metric-value">{summary?.job_count ?? "-"}</div>
        </div>
        <div className="metric">
          <div className="metric-label">Diagrams</div>
          <div className="metric-value">{summary?.diagram_count ?? "-"}</div>
        </div>
        <div className="metric">
          <div className="metric-label">Reports</div>
          <div className="metric-value">{summary?.report_count ?? "-"}</div>
        </div>
      </div>
    </div>
  );
}

function DiagramsPanel({
  diagrams,
  timeline,
  loading,
  timelineOffset,
  timelineTotal,
  onTimelinePage
}: {
  diagrams: DiagramSpec[];
  timeline: TimelineItem[];
  loading: boolean;
  timelineOffset: number;
  timelineTotal: number;
  onTimelinePage: (offset: number) => void;
}) {
  if (loading) {
    return <LoadingMetric label="Diagrams" />;
  }
  const ordered = ["attack_flow", "fund_flow", "evidence_map"];
  const diagramRows = [...diagrams].sort((a, b) => ordered.indexOf(a.diagram_type) - ordered.indexOf(b.diagram_type));
  if (!diagramRows.length) {
    return (
      <div className="form-grid">
        <div className="metric">
          <div className="metric-label">Diagrams</div>
          <div>No diagrams</div>
        </div>
        <TimelineTable timeline={timeline} />
        <Pager offset={timelineOffset} total={timelineTotal} pageSize={PAGE_SIZE} onPage={onTimelinePage} />
      </div>
    );
  }
  return (
    <div className="form-grid">
      {diagramRows.map((diagram) => (
        <ReportPreview
          key={diagram.id}
          content={`## ${diagram.title}\n\n- Confidence: \`${diagram.confidence}\`\n- Evidence: \`${diagram.evidence_ids.length}\`\n\n\`\`\`mermaid\n${diagram.mermaid_source}\n\`\`\``}
        />
      ))}
      {timeline.length > 1 ? (
        <>
          <TimelineTable timeline={timeline} />
          <Pager offset={timelineOffset} total={timelineTotal} pageSize={PAGE_SIZE} onPage={onTimelinePage} />
        </>
      ) : null}
    </div>
  );
}

function TimelineTable({ timeline }: { timeline: TimelineItem[] }) {
  return (
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Phase</th>
              <th>Tx</th>
              <th>Method</th>
              <th>Block</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {timeline.map((item) => (
              <tr key={item.tx_id}>
                <td>
                  <StatusBadge value={item.phase} />
                </td>
                <td className="mono">{item.tx_hash}</td>
                <td>{item.method || "unknown"}</td>
                <td>{item.block_number || "-"}</td>
                <td>{item.evidence_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
  );
}

function EvidencePanel({
  evidence,
  selected,
  loading,
  offset,
  total,
  onPage
}: {
  evidence: Evidence[];
  selected?: Evidence;
  loading: boolean;
  offset: number;
  total: number;
  onPage: (offset: number) => void;
}) {
  if (loading) {
    return <LoadingMetric label="Evidence" />;
  }
  return (
    <div className="form-grid">
      <div className="grid-2">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Type</th>
                <th>Claim</th>
                <th>Producer</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {evidence.map((item) => (
                <tr key={item.id}>
                  <td>{item.source_type}</td>
                  <td>{item.claim_key}</td>
                  <td>{item.producer}</td>
                  <td>
                    <StatusBadge value={item.confidence} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <JsonInspector value={selected ?? {}} />
      </div>
      <Pager offset={offset} total={total} pageSize={PAGE_SIZE} onPage={onPage} />
    </div>
  );
}

function FindingsPanel({
  findings,
  loading,
  canReview,
  onReview,
  offset,
  total,
  onPage
}: {
  findings: Finding[];
  loading: boolean;
  canReview: boolean;
  onReview: (findingId: string, status: string) => void;
  offset: number;
  total: number;
  onPage: (offset: number) => void;
}) {
  if (loading) {
    return <LoadingMetric label="Findings" />;
  }
  return (
    <div className="form-grid">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Finding</th>
              <th>Severity</th>
              <th>Confidence</th>
              <th>Evidence</th>
              <th>Review</th>
              <th>Review Decision</th>
            </tr>
          </thead>
          <tbody>
            {findings.map((item) => (
              <tr key={item.id}>
                <td>
                  <strong>{item.title}</strong>
                  <div>{item.claim}</div>
                </td>
                <td>
                  <StatusBadge value={item.severity} />
                </td>
                <td>
                  <StatusBadge value={item.confidence} />
                </td>
                <td>{item.evidence_ids.length}</td>
                <td>
                  <StatusBadge value={item.reviewer_status} />
                </td>
                <td>
                  {canReview ? (
                    <div className="button-row">
                      <button className="btn" disabled={item.reviewer_status === "approved"} onClick={() => onReview(item.id, "approved")}>
                        <Check size={16} /> Approve
                      </button>
                      <button className="btn danger" disabled={item.reviewer_status === "rejected"} onClick={() => onReview(item.id, "rejected")}>
                        <X size={16} /> Reject
                      </button>
                    </div>
                  ) : (
                    <StatusBadge value="reviewer_only" />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pager offset={offset} total={total} pageSize={PAGE_SIZE} onPage={onPage} />
    </div>
  );
}

function ReportsPanel({
  reports,
  detail,
  exports,
  loading,
  exportError,
  onCreatePdf,
  onDownload,
  pdfPending,
  offset,
  total,
  onPage
}: {
  reports: Report[];
  detail?: Report;
  exports: ReportExport[];
  loading: boolean;
  exportError: string | null;
  onCreatePdf: () => void;
  onDownload: (exportId: string) => void;
  pdfPending: boolean;
  offset: number;
  total: number;
  onPage: (offset: number) => void;
}) {
  const pdf = exports.find((item) => item.format === "pdf");
  if (loading) {
    return <LoadingMetric label="Reports" />;
  }
  return (
    <div className="grid-2">
      <div className="form-grid">
        <div className="button-row">
          <button className="btn" disabled={!detail || pdfPending} onClick={onCreatePdf}>
            <FileText size={16} /> Export PDF
          </button>
          <button className="btn" disabled={!pdf || pdf.status !== "success"} onClick={() => pdf?.id && onDownload(pdf.id)}>
            <Download size={16} /> Download PDF
          </button>
          {pdf ? <StatusBadge value={pdf.status} /> : null}
        </div>
        {exportError ? <div className="badge high">{exportError}</div> : null}
        {pdf?.error ? <div className="badge high">{pdf.error}</div> : null}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Version</th>
                <th>Format</th>
                <th>Status</th>
                <th>Artifact</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((item) => (
                <tr key={item.id}>
                  <td>v{item.version}</td>
                  <td>{item.format}</td>
                  <td>
                    <StatusBadge value={item.status} />
                  </td>
                  <td className="mono">{item.object_path || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pager offset={offset} total={total} pageSize={REPORT_PAGE_SIZE} onPage={onPage} />
      </div>
      {typeof detail?.content === "string" ? <ReportPreview content={detail.content} /> : <div className="markdown">{JSON.stringify(detail?.content ?? {}, null, 2)}</div>}
    </div>
  );
}

function JobsPanel({
  jobs,
  workflowRuns,
  loading,
  offset,
  total,
  onPage
}: {
  jobs: JobRun[];
  workflowRuns: WorkflowRun[];
  loading: boolean;
  offset: number;
  total: number;
  onPage: (offset: number) => void;
}) {
  if (loading) {
    return <LoadingMetric label="Jobs" />;
  }
  return (
    <div className="form-grid">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Workflow</th>
              <th>Mode</th>
              <th>Status</th>
              <th>Started</th>
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            {workflowRuns.map((item) => (
              <tr key={item.id}>
                <td className="mono">{item.workflow_id}</td>
                <td>{item.mode}</td>
                <td>
                  <StatusBadge value={item.status} />
                </td>
                <td>{item.started_at || item.created_at}</td>
                <td>{item.error || "-"}</td>
              </tr>
            ))}
            {!workflowRuns.length ? (
              <tr>
                <td colSpan={5}>No workflow runs</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Job</th>
              <th>Status</th>
              <th>Started</th>
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((item) => (
              <tr key={item.id}>
                <td>{item.job_name}</td>
                <td>
                  <StatusBadge value={item.status} />
                </td>
                <td>{item.started_at || item.created_at}</td>
                <td>{item.error || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pager offset={offset} total={total} pageSize={PAGE_SIZE} onPage={onPage} />
    </div>
  );
}

function Pager({ offset, total, pageSize, onPage }: { offset: number; total: number; pageSize: number; onPage: (offset: number) => void }) {
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + pageSize, total);
  return (
    <div className="button-row">
      <button className="btn" disabled={offset <= 0} onClick={() => onPage(Math.max(0, offset - pageSize))}>
        Previous
      </button>
      <span className="mono">
        {from}-{to} / {total}
      </span>
      <button className="btn" disabled={offset + pageSize >= total} onClick={() => onPage(offset + pageSize)}>
        Next
      </button>
    </div>
  );
}

function LoadingMetric({ label }: { label: string }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div>Loading...</div>
    </div>
  );
}
