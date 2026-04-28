import { CaseDetail, type CaseTab } from "@/components/case-detail";

const validTabs = new Set(["overview", "diagrams", "evidence", "findings", "reports", "jobs"]);

export default function CasePage({ params, searchParams }: { params: { caseId: string }; searchParams?: { tab?: string } }) {
  const requestedTab = searchParams?.tab === "timeline" ? "diagrams" : searchParams?.tab;
  const initialTab = requestedTab && validTabs.has(requestedTab) ? (requestedTab as CaseTab) : "overview";
  return <CaseDetail caseId={params.caseId} initialTab={initialTab} />;
}
