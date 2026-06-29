import { useState, useEffect, useMemo, useCallback, memo, useRef } from "react";
import { useConfigStore } from "@/store/configStore";
import type { WikiTreeNode } from "@/lib/types";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { sourceLinkRenderer } from "@/components/wiki/SourceLink";
import { MermaidRenderer } from "@/components/shared/MermaidRenderer";
import rehypeSourceLinks from "@/components/wiki/rehypeSourceLinks";
import { rehypePrettyCodePlugin } from "@/components/wiki/rehypePrettyCode";

export function WikiPanel() {
  const wikiTree = useConfigStore((s) => s.wikiTree);
  const wikiContent = useConfigStore((s) => s.wikiContent);
  const fetchWikiTree = useConfigStore((s) => s.fetchWikiTree);
  const fetchWikiContent = useConfigStore((s) => s.fetchWikiContent);
  const repoPath = useConfigStore((s) => s.repoPath);

  const [activeDiagram, setActiveDiagram] = useState<
    "architecture" | "classes" | "sequence"
  >("architecture");
  const [diagramData, setDiagramData] = useState<Record<string, string>>({});
  const [activeWikiPath, setActiveWikiPath] = useState<string>("");
  const [activeSourcePath, setActiveSourcePath] = useState<string>("");
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  const [fullscreenDiagram, setFullscreenDiagram] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const panStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 });

  // Stable callbacks for tree nodes (prevents 405 re-renders on click)
  const handleToggleExpand = useCallback((path: string) => {
    setExpandedDirs((prev) => {
      const next = new Set(prev);
      next.has(path) ? next.delete(path) : next.add(path);
      return next;
    });
  }, []);

  const handleFileClick = useCallback((node: WikiTreeNode) => {
    setActiveWikiPath(node.path);
    setActiveSourcePath(node.sourcePath || node.path.replace(/\.md$/, ".py"));
    fetchWikiContent(node.path);
  }, [fetchWikiContent]);

  useEffect(() => {
    if (repoPath) fetchWikiTree();
  }, [repoPath, fetchWikiTree]);

  // Fetch diagram when tab changes
  useEffect(() => {
    async function fetchDiagram() {
      try {
        const endpoints: Record<string, string> = {
          architecture: "/api/diagrams/architecture",
          classes: "/api/diagrams/classes",
          sequence: `/api/diagrams/sequence/${activeSourcePath || "main"}`,
        };
        const res = await fetch(endpoints[activeDiagram]);
        if (res.ok) {
          const data = await res.json();
          setDiagramData((prev) => ({
            ...prev,
            [activeDiagram]: data.mermaid || "",
          }));
        }
      } catch { /* ignore */ }
    }
    fetchDiagram();
  }, [activeDiagram, activeWikiPath, activeSourcePath]);

  // Memoize renderer and markdown to avoid re-parse on tab switches
  const renderer = useMemo(() => sourceLinkRenderer(repoPath), [repoPath]);
  const renderedMarkdown = useMemo(
    () => (
      <article className="prose dark:prose-invert max-w-none text-sm">
        <ReactMarkdown components={renderer} rehypePlugins={[rehypePrettyCodePlugin, rehypeSourceLinks]} remarkPlugins={[remarkGfm]}>{wikiContent}</ReactMarkdown>
      </article>
    ),
    [wikiContent, renderer]
  );

  /** Recursively find a node by its full path in the tree. */
  const findNodeByPath = (nodes: WikiTreeNode[], targetPath: string): WikiTreeNode | null => {
    for (const n of nodes) {
      if (n.path === targetPath) return n;
      if (n.children) {
        const found = findNodeByPath(n.children, targetPath);
        if (found) return found;
      }
    }
    return null;
  };

  if (wikiTree.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground">
        <div className="text-center">
          <p className="text-2xl mb-2">📖</p>
          <p className="text-sm">尚未生成 Wiki 文档</p>
          <p className="text-xs mt-1">分析代码后将自动生成</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex">
      {/* Wiki sidebar */}
      <aside className="w-56 border-r border-border flex flex-col shrink-0">
        <div className="p-3 border-b border-border flex items-center justify-between">
          <h3 className="text-xs font-semibold text-muted-foreground">
            📄 WIKI 页面
          </h3>
          <button
            onClick={async () => {
              const res = await fetch("/api/wiki/tree");
              if (res.ok) {
                const nodes: WikiTreeNode[] = await res.json();
                // Restore active selection if the same path still exists
                if (activeWikiPath) {
                  const found = findNodeByPath(nodes, activeWikiPath);
                  if (found && found.type === "file") {
                    setActiveSourcePath(found.sourcePath || found.path.replace(/\.md$/, ".py"));
                  }
                }
              }
              await fetchWikiTree();
              if (activeWikiPath) {
                fetchWikiContent(activeWikiPath);
              }
            }}
            className="text-xs px-2 py-0.5 rounded hover:bg-accent transition-colors"
            title="刷新 Wiki 列表"
          >
            🔄
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-1">
          {wikiTree.map((node) => (
            <WikiTreeNodeComponent
              key={node.path}
              node={node}
              depth={0}
              activeWikiPath={activeWikiPath}
              expandedDirs={expandedDirs}
              onToggleExpand={handleToggleExpand}
              onFileClick={handleFileClick}
            />
          ))}
        </div>
      </aside>

      {/* Wiki content + diagrams */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Diagram tabs */}
        <div className="flex border-b border-border shrink-0">
          {(["architecture", "classes", "sequence"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveDiagram(tab)}
              className={`px-4 py-2 text-xs transition-colors border-b-2
                ${activeDiagram === tab
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
            >
              {tab === "architecture" && "🏗 架构图"}
              {tab === "classes" && "📊 类图"}
              {tab === "sequence" && "🔄 时序图"}
            </button>
          ))}
        </div>

        {/* Content area */}
        <div className="flex-1 overflow-y-auto">
          {/* Diagram */}
          {diagramData[activeDiagram] && !fullscreenDiagram && (
            <div
              className="p-4 border-b border-border relative group cursor-pointer"
              onClick={() => setFullscreenDiagram(true)}
              style={{ contentVisibility: "auto", containIntrinsicSize: "auto 300px" }}
            >
              <button
                onClick={(e) => { e.stopPropagation(); setFullscreenDiagram(true); }}
                className="absolute top-2 right-2 z-10 px-2 py-1 text-xs rounded border border-input bg-background/80 hover:bg-accent opacity-0 group-hover:opacity-100 transition-opacity"
                title="全屏查看"
              >
                ⛶ 全屏
              </button>
              <MermaidRenderer chart={diagramData[activeDiagram]} />
            </div>
          )}

          {/* Wiki markdown */}
          <div className="p-6">
            {wikiContent ? (
              renderedMarkdown
            ) : (
              <p className="text-sm text-muted-foreground">
                ← 选择左侧 Wiki 页面查看
              </p>
            )}
          </div>
        </div>
      </main>

      {/* Fullscreen diagram overlay */}
      {fullscreenDiagram && diagramData[activeDiagram] && (
        <div
          className="fixed inset-0 z-50 bg-background flex flex-col select-none"
          onClick={(e) => { if (e.target === e.currentTarget) setFullscreenDiagram(false); }}
        >
          <div className="flex items-center justify-between p-3 border-b border-border shrink-0">
            <span className="text-sm font-medium">
              {activeDiagram === "architecture" && "🏗 架构图"}
              {activeDiagram === "classes" && "📊 类图"}
              {activeDiagram === "sequence" && "🔄 时序图"}
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setZoom((z) => Math.max(0.25, z - 0.25))}
                className="px-2 py-1 text-sm rounded border border-input bg-background hover:bg-accent"
                title="缩小"
              >➖</button>
              <span className="text-xs text-muted-foreground w-12 text-center tabular-nums">
                {Math.round(zoom * 100)}%
              </span>
              <button
                onClick={() => setZoom((z) => z + 0.25)}
                className="px-2 py-1 text-sm rounded border border-input bg-background hover:bg-accent"
                title="放大"
              >➕</button>
              <button
                onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}
                className="px-2 py-1 text-sm rounded border border-input bg-background hover:bg-accent"
                title="重置"
              >🔄</button>
              <button
                onClick={() => setFullscreenDiagram(false)}
                className="px-3 py-1 text-sm rounded border border-input bg-background hover:bg-accent ml-2"
              >
                ✕ 关闭
              </button>
            </div>
          </div>
          <div
            className="flex-1 overflow-hidden p-2 flex items-center justify-center"
            onWheel={(e) => {
              e.preventDefault();
              const delta = e.deltaY > 0 ? -0.1 : 0.1;
              setZoom((z) => Math.max(0.25, z + delta));
            }}
            onMouseDown={(e) => {
              if (e.button === 0) {
                setIsPanning(true);
                panStart.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y };
              }
            }}
            onMouseMove={(e) => {
              if (!isPanning) return;
              setPan({
                x: panStart.current.panX + (e.clientX - panStart.current.x),
                y: panStart.current.panY + (e.clientY - panStart.current.y),
              });
            }}
            onMouseUp={() => setIsPanning(false)}
            onMouseLeave={() => setIsPanning(false)}
            style={{ cursor: isPanning ? "grabbing" : zoom > 1 ? "grab" : "default" }}
          >
            <div
              className="w-full h-full"
              style={{
                transform: `scale(${zoom}) translate(${pan.x / zoom}px, ${pan.y / zoom}px)`,
                transformOrigin: "center center",
                transition: isPanning ? "none" : "transform 0.15s ease-out",
              }}
            >
              <MermaidRenderer chart={diagramData[activeDiagram]} className="mermaid-container-fullscreen" />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** Recursive tree node component for wiki sidebar. */
const WikiTreeNodeComponent = memo(function WikiTreeNodeComponent({
  node,
  depth,
  activeWikiPath,
  expandedDirs,
  onToggleExpand,
  onFileClick,
}: {
  node: WikiTreeNode;
  depth: number;
  activeWikiPath: string;
  expandedDirs: Set<string>;
  onToggleExpand: (path: string) => void;
  onFileClick: (node: WikiTreeNode) => void;
}) {
  const isDir = node.type === "directory";
  const isExpanded = expandedDirs.has(node.path);
  const isActive = activeWikiPath === node.path;

  if (isDir) {
    return (
      <div>
        <div
          className="flex items-center gap-1 px-1 py-0.5 cursor-pointer text-xs rounded hover:bg-accent/50 select-none"
          style={{ paddingLeft: `${depth * 16 + 4}px` }}
          onClick={() => onToggleExpand(node.path)}
        >
          <span className="w-4 text-center text-[10px]">{isExpanded ? "▼" : "▶"}</span>
          <span className="text-xs">{isExpanded ? "📂" : "📁"}</span>
          <span className="truncate">{node.name}</span>
        </div>
        {isExpanded && node.children && (
          <div>
            {node.children.map((child) => (
              <WikiTreeNodeComponent
                key={child.path}
                node={child}
                depth={depth + 1}
                activeWikiPath={activeWikiPath}
                expandedDirs={expandedDirs}
                onToggleExpand={onToggleExpand}
                onFileClick={onFileClick}
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  // File node
  return (
    <div>
      <button
        className={`flex items-center gap-1 w-full text-left px-1 py-0.5 text-xs rounded transition-colors truncate
          ${isActive ? "bg-accent" : "hover:bg-accent/50"}`}
        style={{ paddingLeft: `${depth * 16 + 4}px` }}
        onClick={() => onFileClick(node)}
      >
        <span className="w-4 text-center text-[10px]">📄</span>
        <span className="truncate">{node.name}</span>
      </button>
    </div>
  );
});
