export function StatusBadge({ value }: { value: string | null | undefined }) {
  const text = value || "unknown";
  return <span className={`badge ${text}`}>{text}</span>;
}
