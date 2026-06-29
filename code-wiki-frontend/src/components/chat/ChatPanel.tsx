import { SparklesIcon, FolderOpenIcon, PaperclipIcon, XIcon, FileIcon, FolderSyncIcon } from "lucide-react";
import { useConfigStore } from "@/store/configStore";
import { StyledThread } from "@/components/assistant-ui";
import { setAttachedFiles } from "@/lib/chat/sseAdapter";
import { useState, useCallback, useEffect, useRef } from "react";

export function ChatPanel() {
  const wikiPath = useConfigStore((s) => s.wikiPath);
  const setWikiPath = useConfigStore((s) => s.setWikiPath);

  // File attachments — read via Tauri, sent as chat context
  const [files, setFiles] = useState<{ name: string; content: string }[]>([]);
  const watchIdRef = useRef<string | null>(null);
  const watchedDirRef = useRef<string | null>(null);
  const unlistenRef = useRef<(() => void) | null>(null);

  // Start watching + listen for dir-changed events
  useEffect(() => {
    return () => {
      // Cleanup on unmount
      if (unlistenRef.current) unlistenRef.current();
      if (watchIdRef.current) {
        import("@tauri-apps/api/core").then(({ invoke }) => {
          invoke("stop_watch_directory", { watchId: watchIdRef.current }).catch(() => {});
        });
      }
    };
  }, []);

  const refreshDirFiles = useCallback(async (dirPath: string) => {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const dirName = dirPath.split(/[/\\]/).pop() || dirPath;
      const dirFiles: { name: string; path: string; content: string }[] =
        await invoke("read_directory_files", { dirPath });
      if (!dirFiles || dirFiles.length === 0) return;
      const newFiles = dirFiles.map((f) => ({
        name: `${dirName}/${f.path}`,
        content: f.content,
      }));
      setFiles((prev) => {
        // Replace only the files from this watched dir, keep others
        const others = prev.filter((f) => !f.name.startsWith(dirName + "/"));
        const merged = [...others, ...newFiles].slice(0, 5);
        setAttachedFiles(merged);
        return merged;
      });
    } catch { /* watcher re-read failed */ }
  }, []);

  const handleAttach = useCallback(async () => {
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const { invoke } = await import("@tauri-apps/api/core");
      const selected = await open({
        multiple: true,
        title: "选择文档（PDF/Word/TXT/MD 等）",
        filters: [
          { name: "文档", extensions: ["pdf", "docx", "doc", "txt", "md", "csv", "json", "xml", "yaml", "yml", "log", "html", "css", "py", "js", "ts", "tsx", "jsx", "rs", "go", "java", "c", "cpp", "h", "hpp"] },
          { name: "全部", extensions: ["*"] },
        ],
      });
      if (!selected) return;
      const paths = Array.isArray(selected) ? selected : [selected];
      const newFiles: { name: string; content: string }[] = [];
      for (const p of paths) {
        try {
          const content = await invoke<string>("read_document_file", { path: p });
          const name = p.split(/[/\\]/).pop() || p;
          newFiles.push({ name, content });
        } catch (e) {
          console.warn(`Failed to read ${p}:`, e);
        }
      }
      if (newFiles.length > 0) {
        const merged = [...files, ...newFiles].slice(0, 5); // max 5 files
        setFiles(merged);
        setAttachedFiles(merged);
      }
    } catch {
      alert("请手动输入文件路径。\n（Tauri 桌面版支持原生文件选择器。）");
    }
  }, [files]);

  const handleAttachDir = useCallback(async () => {
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const { invoke } = await import("@tauri-apps/api/core");
      const { listen } = await import("@tauri-apps/api/event");
      const selected = await open({
        directory: true,
        multiple: false,
        title: "选择要监听的文件夹",
      });
      if (!selected) return;
      const dirPath = selected as string;
      const dirName = dirPath.split(/[/\\]/).pop() || dirPath;

      // Stop previous watcher if any
      if (watchIdRef.current) {
        await invoke("stop_watch_directory", { watchId: watchIdRef.current }).catch(() => {});
      }
      if (unlistenRef.current) unlistenRef.current();

      // Start watching
      const wId = await invoke<string>("start_watch_directory", { dirPath });
      watchIdRef.current = wId;
      watchedDirRef.current = dirPath;

      // Listen for changes
      let debounceTimer: ReturnType<typeof setTimeout> | null = null;
      const unlisten = await listen<string>("dir-changed", (event) => {
        if (event.payload === dirPath) {
          // Debounce: file save often triggers multiple events
          if (debounceTimer) clearTimeout(debounceTimer);
          debounceTimer = setTimeout(() => {
            refreshDirFiles(dirPath);
          }, 500);
        }
      });
      unlistenRef.current = unlisten;

      // Read files initially
      const dirFiles: { name: string; path: string; content: string }[] =
        await invoke("read_directory_files", { dirPath });
      if (!dirFiles || dirFiles.length === 0) {
        alert(`文件夹 "${dirName}" 中未读取到文本文件。\n将持续监听文件变化。`);
        return;
      }
      const newFiles = dirFiles.map((f) => ({
        name: `${dirName}/${f.path}`,
        content: f.content,
      }));
      setFiles((prev) => {
        const merged = [...prev, ...newFiles].slice(0, 5);
        setAttachedFiles(merged);
        return merged;
      });
    } catch {
      alert("请使用 Tauri 桌面版读取文件夹。");
    }
  }, [refreshDirFiles]);

  const removeFile = useCallback((idx: number) => {
    setFiles((prev) => {
      const next = prev.filter((_, i) => i !== idx);
      setAttachedFiles(next);
      // If no files left, stop watching
      if (next.length === 0 && watchIdRef.current) {
        import("@tauri-apps/api/core").then(({ invoke }) => {
          invoke("stop_watch_directory", { watchId: watchIdRef.current! }).catch(() => {});
        });
        watchIdRef.current = null;
        watchedDirRef.current = null;
        if (unlistenRef.current) {
          unlistenRef.current();
          unlistenRef.current = null;
        }
      }
      return next;
    });
  }, []);

  return (
    <div className="flex flex-col min-h-0 h-full bg-background">
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
        {/* File attachments */}
        <div className="px-4 pb-2 space-y-1">
          <div className="flex gap-1 items-center">
            <button
              type="button"
              onClick={handleAttach}
              className="flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-input bg-background hover:bg-accent transition-colors"
              title="附加本地文件作为聊天上下文（Tauri 桌面版）"
            >
              <PaperclipIcon size={12} />
              附加文件
            </button>
            <button
              type="button"
              onClick={handleAttachDir}
              className="flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-input bg-background hover:bg-accent transition-colors"
              title="附加整个文件夹内容（Tauri 桌面版）"
            >
              <FolderSyncIcon size={12} />
              附加文件夹
            </button>
            <span className="text-[10px] text-muted-foreground">
              附加文档内容作为 AI 上下文
            </span>
          </div>
          {files.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {files.map((f, i) => (
                <span
                  key={i}
                  className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[11px] rounded bg-accent text-accent-foreground"
                >
                  <FileIcon size={10} />
                  <span className="max-w-[120px] truncate">{f.name}</span>
                  <button
                    type="button"
                    onClick={() => removeFile(i)}
                    className="hover:text-destructive"
                    title="移除"
                  >
                    <XIcon size={10} />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Assistant-UI Chat (runtime inherited from AppShell) */}
      <StyledThread />
    </div>
  );
}
