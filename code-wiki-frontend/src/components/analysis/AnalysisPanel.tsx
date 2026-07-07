import { useConfigStore } from "@/store/configStore";

export function AnalysisPanel() {
  const repoPath = useConfigStore((s) => s.repoPath);
  const excludePatterns = useConfigStore((s) => s.excludePatterns);
  const setExcludePatterns = useConfigStore((s) => s.setExcludePatterns);
  const llm = useConfigStore((s) => s.llm);
  const triggerScan = useConfigStore((s) => s.triggerScan);
  const cancelScan = useConfigStore((s) => s.cancelScan);
  const analysisStatus = useConfigStore((s) => s.analysisStatus);

  const isRunning = !["idle", "done", "error", "cancelled"].includes(analysisStatus.status);

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-2xl mx-auto p-6 space-y-8">
        <h2 className="text-lg font-semibold">分析</h2>

        {/* ---- 仓库路径只读展示 ---- */}
        <section className="space-y-3">
          <h3 className="text-sm font-medium">📁 当前仓库</h3>
          <div className="p-3 rounded-md bg-secondary/50 border border-border text-sm">
            <span className="text-muted-foreground">路径: </span>
            <code className="font-mono text-xs">{repoPath || "(未配置 — 请前往「设置」配置仓库路径)"}</code>
          </div>
          {!repoPath && (
            <p className="text-xs text-amber-500">⚠️ 请先在设置页面配置仓库路径后再运行分析</p>
          )}
        </section>

        {/* ---- 排除规则 ---- */}
        <section className="space-y-3">
          <h3 className="text-sm font-medium">🚫 排除规则</h3>
            <label className="text-xs text-muted-foreground">
              排除规则（每行一个 glob 模式）
            </label>
            <textarea
              value={excludePatterns.join("\n")}
              onChange={(e) =>
                setExcludePatterns(e.target.value.split("\n").filter(Boolean))
              }
              rows={5}
              className="w-full mt-1 px-3 py-2 text-sm font-mono rounded-md border border-input bg-background resize-y"
            />
        </section>

        {/* ---- 分析设置 ---- */}
        <section className="space-y-3">
          <h3 className="text-sm font-medium">⚡ 分析设置</h3>
          {analysisStatus.status === "error" && analysisStatus.errorMessage && (
            <div className="p-3 rounded-md bg-destructive/10 border border-destructive/30 text-sm text-destructive">
              {analysisStatus.errorMessage}
            </div>
          )}
          {!llm.api_key && (
            <div className="p-3 rounded-md bg-amber-500/10 border border-amber-500/30 text-sm text-amber-600 dark:text-amber-400">
              ⚠️ 未配置 API Key：分析仍可执行，但不会生成 AI 文档。请前往
              <span className="font-medium"> 设置 → LLM 配置</span> 填写 API Key。
            </div>
          )}
          {isRunning && (
            <div className="space-y-2">
              <div className="h-2 bg-secondary rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary transition-all duration-300"
                  style={{ width: `${(analysisStatus.progress * 100).toFixed(0)}%` }}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                {analysisStatus.currentStep} ({(analysisStatus.progress * 100).toFixed(0)}%)
              </p>
              {analysisStatus.totalWiki > 0 && (
                <p className="text-xs text-muted-foreground">
                  📝 Wiki 生成: {analysisStatus.processedWiki}/{analysisStatus.totalWiki}
                </p>
              )}
              <button
                onClick={cancelScan}
                className="w-full px-4 py-2 text-sm rounded-md border border-destructive/50 text-destructive bg-background hover:bg-destructive/10 transition-colors"
              >
                ⏹ 取消分析
              </button>
            </div>
          )}
          <button
            onClick={() => triggerScan("full")}
            disabled={isRunning || !repoPath}
            className="px-4 py-2 text-sm rounded-md bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            ⚡ 开始全部分析
          </button>
        </section>
      </div>
    </div>
  );
}
