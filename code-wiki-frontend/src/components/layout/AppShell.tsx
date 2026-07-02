import { LeftNav } from "./LeftNav";
import { TopBar } from "./TopBar";
import { StatusBar } from "./StatusBar";
import { useConfigStore } from "@/store/configStore";
import { CodePanel } from "@/components/code/CodePanel";
import { WikiPanel } from "@/components/wiki/WikiPanel";
import { AnalysisPanel } from "@/components/analysis/AnalysisPanel";
import { SettingsPanel } from "@/components/settings/SettingsPanel";
import { KnowledgeGraph } from "@/components/graph/KnowledgeGraph";
import { MetricsPanel } from "@/components/metrics/MetricsPanel";
import { ChatDrawer } from "@/components/chat/ChatDrawer";
import { ChatRuntimeProvider } from "@/components/assistant-ui";
import { useState, useEffect, useRef } from "react";

export function AppShell() {
  const activeTab = useConfigStore((s) => s.activeTab);
  const analysisStatus = useConfigStore((s) => s.analysisStatus);
  const [toast, setToast] = useState<string | null>(null);
  const prevStatus = useRef(analysisStatus.status);

  useEffect(() => {
    const s = analysisStatus.status;
    if (prevStatus.current !== s && s === "done") {
      setToast("✅ 分析完成！");
      setTimeout(() => setToast(null), 4000);
    } else if (prevStatus.current !== s && s === "error") {
      const msg = analysisStatus.errorMessage || "分析失败";
      setToast(`❌ ${msg}`);
      setTimeout(() => setToast(null), 6000);
    }
    prevStatus.current = s;
  }, [analysisStatus.status, analysisStatus.errorMessage]);

  return (
    <ChatRuntimeProvider>
      <div className="h-screen flex flex-col">
        <TopBar />
        <div className="flex flex-1 overflow-hidden">
          <LeftNav />
          <main className="flex-1 min-h-0 overflow-hidden">
            {activeTab === "code" && <CodePanel />}
            {activeTab === "wiki" && <WikiPanel />}
            {activeTab === "analysis" && <AnalysisPanel />}
            {activeTab === "settings" && <SettingsPanel />}
            {activeTab === "graph" && <KnowledgeGraph />}
            {activeTab === "metrics" && <MetricsPanel />}
          </main>
          <ChatDrawer />
        </div>
        <StatusBar />
        {/* Toast notification */}
        {toast && (
          <div className="fixed bottom-16 right-4 px-4 py-2 rounded-lg bg-card border border-border shadow-lg text-sm z-50 animate-in slide-in-from-right">
            {toast}
          </div>
        )}
      </div>
    </ChatRuntimeProvider>
  );
}
