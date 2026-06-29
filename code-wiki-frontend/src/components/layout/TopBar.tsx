import { SunIcon, MoonIcon, MessageCircleIcon, SettingsIcon } from "lucide-react";
import { useConfigStore } from "@/store/configStore";

export function TopBar() {
  const theme = useConfigStore((s) => s.theme);
  const setTheme = useConfigStore((s) => s.setTheme);
  const toggleChat = useConfigStore((s) => s.toggleChat);
  const setActiveTab = useConfigStore((s) => s.setActiveTab);
  const analysisStatus = useConfigStore((s) => s.analysisStatus);

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
          onClick={() => setActiveTab("settings")}
          className="p-2 rounded-md hover:bg-accent transition-colors"
          title="设置"
        >
          <SettingsIcon size={18} />
        </button>
      </div>
    </header>
  );
}
