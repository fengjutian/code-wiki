import { useState, useEffect, useCallback, useMemo, memo } from "react";
import { useConfigStore } from "@/store/configStore";
import type { FileTreeNode } from "@/lib/types";
import { CodeViewer } from "./CodeViewer";

export function CodePanel() {
  const repoPath = useConfigStore((s) => s.repoPath);
  const fileTree = useConfigStore((s) => s.fileTree);
  const fetchFileTree = useConfigStore((s) => s.fetchFileTree);
  const triggerScan = useConfigStore((s) => s.triggerScan);
  const analysisStatus = useConfigStore((s) => s.analysisStatus);
  const viewingFilePath = useConfigStore((s) => s.viewingFilePath);
  const setViewingFile = useConfigStore((s) => s.setViewingFile);
  const fetchCodeContent = useConfigStore((s) => s.fetchCodeContent);

  const [search, setSearch] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  const [treeWidth, setTreeWidth] = useState(320);

  // Fetch file tree on mount and when repoPath changes
  useEffect(() => {
    if (repoPath) fetchFileTree();
  }, [repoPath, fetchFileTree]);

  // Context menu state
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    node: FileTreeNode;
  } | null>(null);

  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  // Close context menu on click outside
  useEffect(() => {
    const handler = () => closeContextMenu();
    window.addEventListener("click", handler);
    return () => window.removeEventListener("click", handler);
  }, [closeContextMenu]);

  // Filter tree by search
  const filterTree = (nodes: FileTreeNode[], query: string): FileTreeNode[] => {
    if (!query) return nodes;
    const q = query.toLowerCase();
    return nodes
      .map((n) => ({
        ...n,
        children: n.children ? filterTree(n.children, q) : undefined,
      }))
      .filter(
        (n) =>
          n.name.toLowerCase().includes(q) ||
          (n.children && n.children.length > 0)
      );
  };

  const filteredTree = useMemo(
    () => filterTree(fileTree, search),
    [fileTree, search]
  );

  // Toggle file selection (Ctrl/Cmd+click)
  const toggleSelect = (path: string, multi: boolean) => {
    setSelectedFiles((prev) => {
      const next = new Set(multi ? prev : []);
      // In single-select mode, the click toggles: selecting this file deselects others
      if (!multi) {
        if (prev.has(path) && prev.size === 1) {
          next.delete(path);  // Deselect if already selected (toggle off)
        } else {
          next.add(path);     // Select (replaces any prior selection)
        }
      } else {
        // Multi-select: toggle this file in/out of the selection set
        if (prev.has(path)) next.delete(path);
        else next.add(path);
      }
      return next;
    });
  };

  // Open file for viewing (single click)
  const openFile = (path: string) => {
    setViewingFile(path);
    fetchCodeContent(path);
  };

  // Analyze selected files
  const analyzeSelected = () => {
    if (selectedFiles.size > 0) {
      triggerScan("partial", Array.from(selectedFiles));
      setSelectedFiles(new Set());
    }
  };

  // Resize tree panel
  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = treeWidth;

    const handleMove = (ev: MouseEvent) => {
      const newWidth = Math.max(200, Math.min(600, startWidth + ev.clientX - startX));
      setTreeWidth(newWidth);
    };
    const handleUp = () => {
      document.removeEventListener("mousemove", handleMove);
      document.removeEventListener("mouseup", handleUp);
    };
    document.addEventListener("mousemove", handleMove);
    document.addEventListener("mouseup", handleUp);
  }, [treeWidth]);

  if (!repoPath) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground">
        <div className="text-center">
          <p className="text-2xl mb-2">📁</p>
          <p className="text-sm">请先在设置中选择仓库路径</p>
        </div>
      </div>
    );
  }

  if (fileTree.length === 0 && analysisStatus.status === "idle") {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground">
        <div className="text-center">
          <p className="text-2xl mb-2">⏳</p>
          <p className="text-sm">点击「开始分析」扫描仓库文件</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex">
      {/* Left: File Tree */}
      <div className="flex flex-col border-r border-border shrink-0" style={{ width: treeWidth }}>
        {/* Toolbar */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-border shrink-0">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索文件..."
            className="flex-1 px-2 py-1 text-sm rounded border border-input bg-background"
          />
          <button
            onClick={() => triggerScan("full")}
            disabled={analysisStatus.status === "scanning"}
            className="px-2 py-1 text-sm rounded hover:bg-accent disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
            title="重新扫描并分析全部文件"
          >
            <span className={analysisStatus.status === "scanning" ? "inline-block animate-spin" : ""}>🔄</span>
          </button>
          {selectedFiles.size > 0 && (
            <button
              onClick={analyzeSelected}
              className="px-3 py-1 text-xs rounded bg-primary text-primary-foreground hover:opacity-90 whitespace-nowrap"
            >
              分析选中 ({selectedFiles.size})
            </button>
          )}
        </div>

        {/* File tree */}
        <div className="flex-1 overflow-y-auto p-1">
          {filteredTree.map((node) => (
            <TreeNode
              key={node.path}
              node={node}
              depth={0}
              selectedFiles={selectedFiles}
              expandedDirs={expandedDirs}
              viewingFilePath={viewingFilePath}
              onToggleSelect={toggleSelect}
              onToggleExpand={(path) =>
                setExpandedDirs((prev) => {
                  const next = new Set(prev);
                  next.has(path) ? next.delete(path) : next.add(path);
                  return next;
                })
              }
              onFileOpen={openFile}
              onContextMenu={(e, n) => {
                e.preventDefault();
                e.stopPropagation();
                setContextMenu({ x: e.clientX, y: e.clientY, node: n });
              }}
            />
          ))}
          {filteredTree.length === 0 && search && (
            <p className="text-sm text-muted-foreground text-center py-4">
              未找到匹配 "{search}"
            </p>
          )}
        </div>
      </div>

      {/* Resize handle */}
      {viewingFilePath && (
        <div
          className="w-1 cursor-col-resize bg-border hover:bg-primary/50 active:bg-primary shrink-0"
          onMouseDown={handleResizeStart}
        />
      )}

      {/* Right: Code Viewer */}
      <div className="flex-1 overflow-hidden">
        <CodeViewer />
      </div>

      {/* Context menu */}
      {contextMenu && (
        <div
          className="fixed z-50 bg-popover border border-border rounded-md shadow-lg py-1 min-w-[160px]"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent"
            onClick={() => {
              openFile(contextMenu.node.path);
              closeContextMenu();
            }}
          >
            📖 查看代码
          </button>
          <div className="border-t border-border my-1" />
          <button
            className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent"
            onClick={() => {
              triggerScan("partial", [contextMenu.node.path]);
              closeContextMenu();
            }}
          >
            📊 分析此文件
          </button>
          {contextMenu.node.type === "directory" && (
            <button
              className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent"
              onClick={() => {
                // Get all .py files recursively under this dir
                const collectFiles = (n: FileTreeNode): string[] => {
                  if (n.type === "file") return [n.path];
                  return (n.children || []).flatMap(collectFiles);
                };
                const files = collectFiles(contextMenu.node);
                triggerScan("partial", files);
                closeContextMenu();
              }}
            >
              📊 分析此目录
            </button>
          )}
          <div className="border-t border-border my-1" />
          <button
            className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent"
            onClick={() => {
              // Add to exclude patterns
              const store = useConfigStore.getState();
              const pattern = contextMenu.node.type === "directory"
                ? contextMenu.node.path + "/"
                : contextMenu.node.path;
              store.setExcludePatterns([...store.excludePatterns, pattern]);
              closeContextMenu();
            }}
          >
            🚫 排除此{contextMenu.node.type === "directory" ? "目录" : "文件"}
          </button>
        </div>
      )}
    </div>
  );
}

// ---- Tree Node Component ----
const TreeNode = memo(function _TreeNode({
  node,
  depth,
  selectedFiles,
  expandedDirs,
  viewingFilePath,
  onToggleSelect,
  onToggleExpand,
  onFileOpen,
  onContextMenu,
}: {
  node: FileTreeNode;
  depth: number;
  selectedFiles: Set<string>;
  expandedDirs: Set<string>;
  viewingFilePath: string | null;
  onToggleSelect: (path: string, multi: boolean) => void;
  onToggleExpand: (path: string) => void;
  onFileOpen: (path: string) => void;
  onContextMenu: (e: React.MouseEvent, node: FileTreeNode) => void;
}) {
  const isDir = node.type === "directory";
  const isExpanded = expandedDirs.has(node.path);
  const isSelected = selectedFiles.has(node.path);
  const isViewing = viewingFilePath === node.path;

  return (
    <div>
      <div
        className={`flex items-center gap-1 px-1 py-0.5 cursor-pointer text-sm rounded select-none
          ${isSelected ? "bg-accent" : isViewing ? "bg-primary/10" : "hover:bg-accent/50"}
          ${node.excluded ? "opacity-40 line-through" : ""}
        `}
        style={{ paddingLeft: `${depth * 16 + 4}px` }}
        onClick={(e) => {
          if (isDir) {
            onToggleExpand(node.path);
          } else if (e.ctrlKey || e.metaKey) {
            onToggleSelect(node.path, true);
          } else {
            onFileOpen(node.path);
          }
        }}
        onContextMenu={(e) => onContextMenu(e, node)}
      >
        {/* Expand arrow for dirs */}
        <span className="w-4 text-center text-[10px]">
          {isDir ? (isExpanded ? "▼" : "▶") : "📄"}
        </span>

        {/* Icon */}
        <span className="text-xs">{isDir ? (isExpanded ? "📂" : "📁") : null}</span>

        {/* Name */}
        <span className="truncate">{node.name}</span>

        {/* Status for files */}
        {!isDir && (
          <span className="ml-auto text-[10px] shrink-0">
            {node.status === "analyzed" && "✅"}
            {node.status === "pending" && "⏳"}
            {node.status === "analyzing" && "🔄"}
          </span>
        )}
      </div>

      {/* Children */}
      {isDir && isExpanded && node.children && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedFiles={selectedFiles}
              expandedDirs={expandedDirs}
              viewingFilePath={viewingFilePath}
              onToggleSelect={onToggleSelect}
              onToggleExpand={onToggleExpand}
              onFileOpen={onFileOpen}
              onContextMenu={onContextMenu}
            />
          ))}
        </div>
      )}
    </div>
  );
});
