export function StatusBadge({ value }: { value: string | null | undefined }) {
  const text = value || "unknown";
  return <span className={`badge ${text}`}>{statusLabel(text)}</span>;
}

function statusLabel(value: string) {
  const labels: Record<string, string> = {
    critical: "严重",
    high: "高",
    medium: "中",
    low: "低",
    info: "信息",
    unknown: "未知",
    partial: "部分",
    success: "成功",
    failed: "失败",
    running: "运行中",
    pending: "待处理",
    approved: "已通过",
    rejected: "已拒绝",
    reviewer_only: "仅复核员",
    draft: "草稿",
    published: "已发布",
    CREATED: "已创建",
    PARTIAL: "部分完成",
    REPORT_DRAFTED: "报告已生成",
    FAILED: "失败",
    CANCELLED: "已取消"
  };
  return labels[value] || value;
}
