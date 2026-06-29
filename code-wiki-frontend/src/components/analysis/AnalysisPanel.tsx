import { useConfigStore } from "@/store/configStore";

export function AnalysisPanel() {
  const repoPath = useConfigStore((s) => s.repoPath);
  const setRepoPath = useConfigStore((s) => s.setRepoPath);
  const wikiPath = useConfigStore((s) => s.wikiPath);
  const setWikiPath = useConfigStore((s) => s.setWikiPath);
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

        {/* ---- 仓库配置 ---- */}
        <section className="space-y-3">
          <h3 className="text-sm font-medium">📁 仓库配置</h3>
          <div>
            <label className="text-xs text-muted-foreground">仓库路径</label>
            <div className="flex gap-2 mt-1">
              <input
                type="text"
                value={repoPath}
                onChange={(e) => setRepoPath(e.target.value)}
                placeholder="输入或粘贴仓库路径..."
                className="flex-1 px-3 py-2 text-sm rounded-md border border-input bg-background"
              />
              <button
                type="button"
                onClick={async () => {
                  // Try Tauri native dialog (when @tauri-apps/plugin-dialog is installed)
                  try {
                    const { open } = await import("@tauri-apps/plugin-dialog");
                    const selected = await open({ directory: true, multiple: false, title: "选择仓库目录" });
                    if (selected) setRepoPath(selected as string);
                  } catch {
                    // In browser dev mode, native dialog is unavailable.
                    // Browser security does not expose the full filesystem path,
                    // so the user must paste the path manually.
                    alert("请手动输入或粘贴仓库路径到上方输入框中。\n\n（在 Tauri 桌面版中，此按钮将打开原生文件夹选择器。）");
                  }
                }}
                className="shrink-0 px-3 py-2 text-sm rounded-md border border-input bg-background hover:bg-accent transition-colors"
                title="从本地选择仓库目录"
              >
                📂 浏览
              </button>
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">
              Wiki 输出目录（.code-wiki 的父目录，留空则放在仓库根目录）
            </label>
            <div className="flex gap-2 mt-1">
              <input
                type="text"
                value={wikiPath}
                onChange={(e) => setWikiPath(e.target.value)}
                placeholder="留空 = {仓库路径}/.code-wiki"
                className="flex-1 px-3 py-2 text-sm rounded-md border border-input bg-background"
              />
              <button
                type="button"
                onClick={async () => {
                  try {
                    const { open } = await import("@tauri-apps/plugin-dialog");
                    const selected = await open({ directory: true, multiple: false, title: "选择 Wiki 输出目录" });
                    if (selected) setWikiPath(selected as string);
                  } catch {
                    alert("请手动输入或粘贴 Wiki 输出目录路径。\n\n（在 Tauri 桌面版中，此按钮将打开原生文件夹选择器。）");
                  }
                }}
                className="shrink-0 px-3 py-2 text-sm rounded-md border border-input bg-background hover:bg-accent transition-colors"
                title="从本地选择 Wiki 输出目录"
              >
                📂 浏览
              </button>
            </div>
          </div>
          <div>
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
          </div>
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
