import { cn } from "@/lib/utils";

interface StatusBadgeProps {
  status: "analyzed" | "pending" | "analyzing";
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const colors = {
    analyzed: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
    pending: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
    analyzing: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  };

  const labels = {
    analyzed: "✅ 已分析",
    pending: "⏳ 未分析",
    analyzing: "🔄 分析中",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center px-1.5 py-0.5 text-[10px] rounded-full",
        colors[status],
        className
      )}
    >
      {labels[status]}
    </span>
  );
}
