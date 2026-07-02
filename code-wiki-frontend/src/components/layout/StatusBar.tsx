import { useConfigStore } from "@/store/configStore";
import { useEffect, useState } from "react";
import { Activity } from "lucide-react";

export function StatusBar() {
  const analysisStatus = useConfigStore((s) => s.analysisStatus);
  const [healthScore, setHealthScore] = useState<number | null>(null);

  // Fetch health metrics when analysis completes
  useEffect(() => {
    if (analysisStatus.status !== "done") return;
    (async () => {
      try {
        const res = await fetch("/api/metrics/health");
        if (res.ok) {
          const data = await res.json();
          if (typeof data.health_score === "number") {
            setHealthScore(Math.round(data.health_score));
          }
        }
      } catch { /* ignore */ }
    })();
  }, [analysisStatus.status]);

  const statusText = {
    idle: "⚪ 就绪 — 选择仓库后开始分析",
    scanning: "🔍 正在扫描文件...",
    analyzing: "⚙ 正在分析代码...",
    generating: "📝 正在生成 Wiki...",
    done: "✅ Wiki 已是最新",
    error: `❌ 分析失败: ${analysisStatus.errorMessage || "未知错误"}`,
  }[analysisStatus.status];

  const timeText = analysisStatus.finishedAt
    ? `上次更新: ${new Date(analysisStatus.finishedAt).toLocaleString()}`
    : analysisStatus.startedAt
      ? `开始于: ${new Date(analysisStatus.startedAt).toLocaleString()}`
      : "";

  const scoreColor =
    healthScore === null ? "" :
    healthScore >= 80 ? "text-green-500" :
    healthScore >= 50 ? "text-yellow-500" : "text-red-500";

  return (
    <footer className="h-7 border-t border-border flex items-center justify-between px-4 bg-background shrink-0 text-xs text-muted-foreground">
      <span>{statusText}</span>
      <div className="flex items-center gap-3">
        {healthScore !== null && (
          <span className={`flex items-center gap-1 ${scoreColor}`} title="项目健康度评分">
            <Activity size={12} />
            健康度: {healthScore}/100
          </span>
        )}
        <span>{timeText}</span>
      </div>
    </footer>
  );
}
