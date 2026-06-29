import { CodeIcon, BookOpenIcon, SettingsIcon, BarChart3Icon, MessageCircleIcon, ActivityIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { useConfigStore } from "@/store/configStore";

const tabs = [
  { id: "chat" as const, label: "AI 问答", icon: MessageCircleIcon },
  { id: "analysis" as const, label: "分析", icon: BarChart3Icon },
  { id: "code" as const, label: "Code", icon: CodeIcon },
  { id: "wiki" as const, label: "Wiki", icon: BookOpenIcon },
  { id: "settings" as const, label: "设置", icon: SettingsIcon },
  { id: "test" as const, label: "测试", icon: ActivityIcon },
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
