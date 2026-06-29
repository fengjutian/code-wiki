import { useConfigStore } from "@/store/configStore";

export function StatusBar() {
  const analysisStatus = useConfigStore((s) => s.analysisStatus);

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

  return (
    <footer className="h-7 border-t border-border flex items-center justify-between px-4 bg-background shrink-0 text-xs text-muted-foreground">
      <span>{statusText}</span>
      <span>{timeText}</span>
    </footer>
  );
}
