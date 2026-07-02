import { SunIcon, MoonIcon, MessageCircleIcon, SettingsIcon, XIcon } from "lucide-react";
import { useConfigStore } from "@/store/configStore";
import { useState } from "react";
import { SettingsPanel } from "@/components/settings/SettingsPanel";

export function TopBar() {
  const theme = useConfigStore((s) => s.theme);
  const setTheme = useConfigStore((s) => s.setTheme);
  const toggleChat = useConfigStore((s) => s.toggleChat);
  const analysisStatus = useConfigStore((s) => s.analysisStatus);
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <header className="h-12 border-b border-border flex items-center justify-between px-4 bg-background shrink-0">
      <div className="flex items-center gap-3">
        <h1 className="font-semibold text-sm tracking-tight">Code Wiki</h1>
        {analysisStatus.status !== "idle" && analysisStatus.status !== "done" && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-accent text-accent-foreground">
            {analysisStatus.status === "scanning" && "🔍 扫描中"}
            {analysisStatus.status === "analyzing" && "⚙ 分析中"}
            {analysisStatus.status === "generating" && "📝 生成中"}
          </span>
        )}
      </div>

      <div className="flex items-center gap-1">
        <button
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          className="p-2 rounded-md hover:bg-accent transition-colors"
          title="切换主题"
        >
          {theme === "dark" ? <SunIcon size={18} /> : <MoonIcon size={18} />}
        </button>

        <button
          onClick={toggleChat}
          className="p-2 rounded-md hover:bg-accent transition-colors"
          title="AI 问答"
        >
          <MessageCircleIcon size={18} />
        </button>

        <button
          onClick={() => setSettingsOpen(true)}
          className="p-2 rounded-md hover:bg-accent transition-colors"
          title="设置"
        >
          <SettingsIcon size={18} />
        </button>
      </div>

      {/* Settings Dialog */}
      {settingsOpen && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[10vh]">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={() => setSettingsOpen(false)}
          />
          {/* Panel */}
          <div className="relative bg-card border border-border rounded-xl shadow-2xl w-[620px] max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 py-3 border-b border-border sticky top-0 bg-card z-10">
              <h2 className="font-semibold text-sm">⚙ 设置</h2>
              <button
                onClick={() => setSettingsOpen(false)}
                className="p-1 rounded-md hover:bg-accent transition-colors"
              >
                <XIcon size={16} />
              </button>
            </div>
            <div className="p-5">
              <SettingsPanel />
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
