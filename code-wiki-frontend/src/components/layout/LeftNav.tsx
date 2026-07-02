import { CodeIcon, BookOpenIcon, SettingsIcon, BarChart3Icon, GitGraphIcon, ActivityIcon, GaugeIcon, GitBranchIcon, SearchIcon, AlertTriangleIcon, LightbulbIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { useConfigStore } from "@/store/configStore";

const tabs = [
  { id: "analysis" as const, label: "分析", icon: BarChart3Icon },
  { id: "code" as const, label: "Code", icon: CodeIcon },
  { id: "wiki" as const, label: "Wiki", icon: BookOpenIcon },
  { id: "graph" as const, label: "图谱", icon: GitGraphIcon },
  { id: "cfg" as const, label: "CFG", icon: GitBranchIcon },
  { id: "search" as const, label: "搜索", icon: SearchIcon },
  { id: "impact" as const, label: "影响", icon: AlertTriangleIcon },
  { id: "metrics" as const, label: "指标", icon: GaugeIcon },
  { id: "settings" as const, label: "设置", icon: SettingsIcon },
  { id: "test" as const, label: "检测", icon: ActivityIcon },
  { id: "guide" as const, label: "指南", icon: LightbulbIcon },
];

export function LeftNav() {
  const activeTab = useConfigStore((s) => s.activeTab);
  const setActiveTab = useConfigStore((s) => s.setActiveTab);

  return (
    <nav className="w-16 flex flex-col items-center py-4 gap-1 bg-secondary border-r border-border shrink-0">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => setActiveTab(tab.id)}
          title={tab.label}
          className={cn(
            "flex flex-col items-center gap-0.5 w-14 py-2 rounded-lg transition-colors",
            "text-[10px] font-normal",
            activeTab === tab.id
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
          )}
        >
          <tab.icon size={20} />
          <span>{tab.label}</span>
        </button>
      ))}
    </nav>
  );
}
