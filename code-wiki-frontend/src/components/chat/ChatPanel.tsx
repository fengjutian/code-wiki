import { SparklesIcon, FolderOpenIcon } from "lucide-react";
import { useConfigStore } from "@/store/configStore";
import { StyledThread } from "@/components/assistant-ui";

export function ChatPanel() {
  const wikiPath = useConfigStore((s) => s.wikiPath);
  const setWikiPath = useConfigStore((s) => s.setWikiPath);

  return (
    <div className="flex flex-col h-full bg-background">
      {/* Header */}
      <div className="border-b border-border shrink-0">
        <div className="h-10 flex items-center px-4 gap-2">
          <SparklesIcon size={16} className="text-primary" />
          <span className="text-sm font-medium">AI 问答</span>
          <span className="text-[10px] text-muted-foreground">
            基于 Wiki 知识库回答代码问题
          </span>
        </div>
        {/* Wiki path config */}
        <div className="px-4 pb-2">
          <div className="flex gap-1 items-center">
            <FolderOpenIcon size={12} className="text-muted-foreground shrink-0" />
            <input
              type="text"
              value={wikiPath}
              onChange={(e) => setWikiPath(e.target.value)}
              placeholder="Wiki 路径（默认 {仓库}/.code-wiki）"
              className="flex-1 px-2 py-1 text-[11px] rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <button
              type="button"
              onClick={async () => {
                try {
                  const { open } = await import("@tauri-apps/plugin-dialog");
                  const selected = await open({ directory: true, multiple: false, title: "选择 Wiki 目录" });
                  if (selected) setWikiPath(selected as string);
                } catch {
                  alert("请手动输入 Wiki 路径。\n（Tauri 桌面版支持原生文件夹选择器。）");
                }
              }}
              className="shrink-0 px-1.5 py-1 text-[11px] rounded border border-input bg-background hover:bg-accent transition-colors"
              title="选择 Wiki 目录"
            >
              📂
            </button>
          </div>
        </div>
      </div>

      {/* Assistant-UI Chat (runtime inherited from AppShell) */}
      <StyledThread />
    </div>
  );
}
