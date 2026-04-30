"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { apiFetch, CaseRecord, CaseSummary, Network, Role } from "@/lib/api";
import { Shell } from "@/components/shell";
import { StatusBadge } from "@/components/status-badge";

type CaseForm = {
  title: string;
  network_key: string;
  seed_type: "transaction" | "address" | "alert";
  seed_value: string;
  time_window_hours: number;
  depth: "quick" | "full" | "full_replay";
  language: string;
};

const emptyForm: CaseForm = {
  title: "",
  network_key: "megaeth",
  seed_type: "transaction",
  seed_value: "",
  time_window_hours: 8,
  depth: "full",
  language: "zh-CN"
};

const seedTypeOptions: Array<{ value: CaseForm["seed_type"]; label: string }> = [
  { value: "transaction", label: "交易哈希 / Digest" },
  { value: "address", label: "地址" },
  { value: "alert", label: "外部事件链接" }
];
const CASE_PAGE_SIZE = 50;

export function Dashboard() {
  const [role, setRole] = useState<Role>("admin");
  const [form, setForm] = useState<CaseForm>(emptyForm);
  const [caseOffset, setCaseOffset] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const queryClient = useQueryClient();
  const networks = useQuery({ queryKey: ["networks", role], queryFn: () => apiFetch<Network[]>("/networks", {}, role) });
  const summary = useQuery({ queryKey: ["cases-summary", role], queryFn: () => apiFetch<CaseSummary>("/cases/summary", {}, role) });
  const cases = useQuery({ queryKey: ["cases", role, caseOffset], queryFn: () => apiFetch<CaseRecord[]>(`/cases?limit=${CASE_PAGE_SIZE}&offset=${caseOffset}`, {}, role) });
  const networkRows = networks.data ?? [];
  const caseRows = cases.data ?? [];
  const selectedNetwork = networkRows.find((network) => network.key === form.network_key);
  const seedHelp = seedInputHelp(form.seed_type, selectedNetwork);
  const seedValidationError = seedValidationMessage(form.seed_type, form.seed_value, selectedNetwork);
  const createCase = useMutation({
    mutationFn: () =>
      apiFetch<CaseRecord>(
        "/cases",
        {
          method: "POST",
          body: JSON.stringify({
            ...form,
            title: form.title.trim() || null,
            seed_value: form.seed_value.trim(),
            time_window_hours: 6,
            depth: "full"
          })
        },
        role
      ),
    onSuccess: () => {
      setForm(emptyForm);
      setCaseOffset(0);
      queryClient.invalidateQueries({ queryKey: ["cases", role] });
      queryClient.invalidateQueries({ queryKey: ["cases-summary", role] });
    }
  });
  const totalCases = summary.data?.total_cases ?? caseRows.length;
  const critical = summary.data?.high_severity ?? caseRows.filter((item) => ["critical", "high"].includes(item.severity)).length;
  const reviewQueue = summary.data?.review_queue ?? caseRows.filter((item) => ["REPORT_DRAFTED", "UNDER_REVIEW", "PARTIAL"].includes(item.status)).length;

  useEffect(() => {
    if (!networkRows.length) {
      return;
    }
    if (!networkRows.some((network) => network.key === form.network_key)) {
      setForm((current) => ({ ...current, network_key: networkRows[0].key }));
    }
  }, [form.network_key, networkRows]);

  async function refreshLibrary() {
    setRefreshing(true);
    try {
      await Promise.all([networks.refetch(), summary.refetch(), cases.refetch()]);
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <Shell role={role} onRoleChange={setRole} caseNavCaseId={caseRows[0]?.id}>
      <div className="content">
        <section className="grid-3">
          <div className="metric">
            <div className="metric-label">Cases</div>
            <div className="metric-value">{totalCases}</div>
          </div>
          <div className="metric">
            <div className="metric-label">High Severity</div>
            <div className="metric-value">{critical}</div>
          </div>
          <div className="metric">
            <div className="metric-label">Review Queue</div>
            <div className="metric-value">{reviewQueue}</div>
          </div>
        </section>

        <section className="grid-2">
          <div className="band">
            <div className="band-header">
              <div className="band-title">新建分析</div>
            </div>
            <div className="band-body">
              <div className="form-grid">
                <div className="field">
                  <label>网络</label>
                  <select
                    value={networkRows.some((network) => network.key === form.network_key) ? form.network_key : ""}
                    disabled={networks.isLoading || networks.isError || !networkRows.length}
                    onChange={(event) => setForm({ ...form, network_key: event.target.value })}
                  >
                    {networks.isLoading ? <option value="">Loading networks...</option> : null}
                    {networks.isError ? <option value="">Network API unavailable</option> : null}
                    {!networks.isLoading && !networks.isError && !networkRows.length ? <option value="">No networks configured</option> : null}
                    {networkRows.map((network) => (
                      <option key={network.key} value={network.key}>
                        {network.key} · {network.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label>入口类型</label>
                  <div className="segmented seed-type">
                    {seedTypeOptions.map((type) => (
                      <button
                        key={type.value}
                        className={form.seed_type === type.value ? "active" : ""}
                        onClick={() => setForm({ ...form, seed_type: type.value, seed_value: "" })}
                      >
                        {type.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="field">
                  <label>入口值</label>
                  <input
                    value={form.seed_value}
                    onChange={(event) => setForm({ ...form, seed_value: event.target.value })}
                    placeholder={seedHelp.placeholder}
                  />
                  <div className="field-hint">{seedHelp.description}</div>
                  {seedValidationError ? <div className="field-error">{seedValidationError}</div> : null}
                </div>
                <div className="field">
                  <label>标题</label>
                  <input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} placeholder="可选；留空时系统自动生成" />
                </div>
                <div className="form-note">
                  创建时默认使用 `full` 分析深度。时间窗口字段当前只保留在后端兼容层，Dashboard 不再展示，避免误解为已参与交易发现过滤。
                </div>
                <button
                  className="btn primary"
                  disabled={!form.seed_value.trim() || Boolean(seedValidationError) || !networkRows.length || createCase.isPending}
                  onClick={() => createCase.mutate()}
                >
                  <Plus size={16} /> {createCase.isPending ? "创建中" : "创建 Case"}
                </button>
                {networks.error ? <div className="badge high">{networks.error.message}</div> : null}
                {createCase.error ? <div className="badge high">{createCase.error.message}</div> : null}
              </div>
            </div>
          </div>

          <div className="band">
            <div className="band-header">
              <div className="band-title">Case Library</div>
              <button className="btn" disabled={refreshing} onClick={() => refreshLibrary()}>
                <RefreshCw size={16} /> {refreshing ? "Refreshing" : "Refresh"}
              </button>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Case</th>
                    <th>Network</th>
                    <th>Status</th>
                    <th>Severity</th>
                    <th>Seed</th>
                  </tr>
                </thead>
                <tbody>
                  {caseRows.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <Link href={`/cases/${item.id}`}>
                          <strong>{item.title || item.id}</strong>
                        </Link>
                        <div className="mono">{item.id}</div>
                      </td>
                      <td>{item.network_key}</td>
                      <td>
                        <StatusBadge value={item.status} />
                      </td>
                      <td>
                        <StatusBadge value={item.severity} />
                      </td>
                      <td className="mono">
                        {item.seed_type}: {item.seed_value}
                      </td>
                    </tr>
                  ))}
                  {!caseRows.length ? (
                    <tr>
                      <td colSpan={5}>No cases</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
            {totalCases > CASE_PAGE_SIZE ? (
              <div className="band-body">
                <div className="button-row">
                  <button className="btn" disabled={caseOffset <= 0} onClick={() => setCaseOffset((value) => Math.max(0, value - CASE_PAGE_SIZE))}>
                    Previous
                  </button>
                  <span className="mono">
                    {totalCases === 0 ? 0 : caseOffset + 1}-{Math.min(caseOffset + CASE_PAGE_SIZE, totalCases)} / {totalCases}
                  </span>
                  <button className="btn" disabled={caseOffset + CASE_PAGE_SIZE >= totalCases} onClick={() => setCaseOffset((value) => value + CASE_PAGE_SIZE)}>
                    Next
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </Shell>
  );
}

function seedInputHelp(seedType: CaseForm["seed_type"], network: Network | undefined): { placeholder: string; description: string } {
  if (seedType === "transaction") {
    if (network?.network_type === "sui") {
      return {
        placeholder: "例如 6WNDjCX3W852hipq6yrHhpUaSFHSPWfTxuLKaQkgNfVL",
        description: "Sui 网络会使用 Sui JSON-RPC 拉取 transaction block、events 和 balanceChanges。"
      };
    }
    return {
      placeholder: "例如 0x1c27c4d625429acfc0f97e466eda725fd09ebdc77550e529ba4cbdbc33beb97b",
      description: "EVM 网络会先验证交易、拉取 receipt，再按网络能力运行 TxAnalyzer 或 fallback artifact。"
    };
  }
  if (seedType === "address") {
    return {
      placeholder: network?.network_type === "sui" ? "例如 0x27bc7a3c..." : "例如 0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
      description: "用于从地址发现相关交易。EVM 地址发现依赖对应 Explorer API key；Sui 地址发现后续会接 native adapter。"
    };
  }
  return {
    placeholder: "例如 https://defillama.com/hacks 或官方 postmortem 链接",
    description: "适合还没有 seed transaction 时先建案；系统会把该链接记录为 external alert evidence。"
  };
}

function seedValidationMessage(seedType: CaseForm["seed_type"], value: string, network: Network | undefined): string | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  if (seedType === "transaction" && network?.network_type === "sui") {
    return /^[1-9A-HJ-NP-Za-km-z]{32,64}$/.test(trimmed) ? null : "请输入 Sui transaction digest，不是 0x 开头的 EVM 交易哈希。";
  }
  if (seedType === "transaction") {
    return /^0x[a-fA-F0-9]{64}$/.test(trimmed) ? null : "请输入 66 位 EVM 交易哈希，格式为 0x + 64 个十六进制字符。";
  }
  if (seedType === "alert") {
    return /^https?:\/\/\S+$/i.test(trimmed) ? null : "请输入以 http:// 或 https:// 开头的公开事件链接。";
  }
  return null;
}
