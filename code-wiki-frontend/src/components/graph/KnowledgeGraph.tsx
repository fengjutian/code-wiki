import { useEffect, useRef, useState, useCallback } from "react";
import cytoscape, { type Core } from "cytoscape";
import { useConfigStore } from "@/store/configStore";
import { Search, ZoomIn, ZoomOut, Maximize, GitBranch, Box } from "lucide-react";

// ---- Module-level cache — survives tab switches without re-fetching ----
let _cachedGraphData: GraphData | null = null;
let _cacheTimestamp = 0;
const CACHE_TTL = 300_000; // 5 minutes

// ---- Layout presets ----
type LayoutName = "cose" | "breadthfirst" | "concentric" | "circle" | "grid";

const LAYOUTS: { id: LayoutName; label: string }[] = [
  { id: "cose", label: "力导向" },
  { id: "breadthfirst", label: "层级" },
  { id: "concentric", label: "同心圆" },
  { id: "circle", label: "环形" },
  { id: "grid", label: "网格" },
];

// ---- Graph data types ----
interface GraphNode {
  id: string;
  label: string;
  layer: string;
  color: string;
  entityCount: number;
  language: string;
}
interface GraphEdge {
  source: string;
  target: string;
  type: string;
}
interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ---- Transform raw analysis.json → GraphData (for Tauri local file path) ----
interface RawModule {
  classes?: unknown[]; functions?: unknown[]; interfaces?: unknown[]; components?: unknown[];
  language?: string;
}
interface RawEdge { source: string; targets: string[]; }
interface AnalysisData { modules: Record<string, RawModule>; dependency_graph?: { edges: RawEdge[] }; }

function transformAnalysis(data: AnalysisData): GraphData {
  const { modules, dependency_graph } = data;
  const modPaths = Object.keys(modules);
  const LAYER_COLORS: Record<string, string> = {
    routes: "#0288d1", services: "#388e3c", models: "#f57c00",
    frontend: "#7b1fa2", config: "#c62828", other: "#616161",
  };
  function classifyLayer(path: string): string {
    const norm = path.replace(/\\/g, "/");
    if (norm.startsWith("routes/")) return "routes";
    if (norm.startsWith("services/")) return "services";
    if (norm.startsWith("models/")) return "models";
    if (norm.startsWith("src/") || norm.includes("frontend")) return "frontend";
    if (norm.startsWith("config") || norm.startsWith("main")) return "config";
    return "other";
  }
  const nodes: GraphNode[] = modPaths.map((path) => {
    const mod = modules[path];
    const layer = classifyLayer(path);
    return {
      id: path, label: path.replace(/\\/g, "/"), layer,
      color: LAYER_COLORS[layer] || LAYER_COLORS.other,
      entityCount: (mod.classes?.length ?? 0) + (mod.functions?.length ?? 0) + (mod.interfaces?.length ?? 0) + (mod.components?.length ?? 0),
      language: mod.language ?? "python",
    };
  });
  const modSet = new Set(modPaths);
  const edges: GraphEdge[] = [];
  for (const entry of dependency_graph?.edges ?? []) {
    for (const tgt of entry.targets) {
      if (modSet.has(entry.source) && modSet.has(tgt)) {
        edges.push({ source: entry.source, target: tgt, type: "imports" });
      }
    }
  }
  return { nodes, edges };
}

export function KnowledgeGraph() {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const repoPath = useConfigStore((s) => s.repoPath);
  const wikiPath = useConfigStore((s) => s.wikiPath);
  const [layout, setLayout] = useState<LayoutName>("cose");
  const [search, setSearch] = useState("");
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [graphMode, setGraphMode] = useState<"module" | "call">("module");

  // ---- Load analysis.json: Tauri local file → HTTP API fallback ----
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Use cache if fresh
        if (_cachedGraphData && Date.now() - _cacheTimestamp < CACHE_TTL && graphMode === "module") {
          setGraphData(_cachedGraphData);
          setLoading(false);
          return;
        }

        let data: GraphData | null = null;

        if (graphMode === "call") {
          // Fetch call-graph data from backend API
          const res = await fetch("/api/metrics/call-graph");
          if (!res.ok) throw new Error(`${res.status}`);
          const cg = await res.json();
          if (!cg.callables || Object.keys(cg.callables).length === 0) {
            setError("暂无函数调用图数据，请先运行分析");
            setLoading(false);
            return;
          }
          // Transform call-graph to graph data format
          const callGraphNodes: GraphNode[] = Object.entries(cg.callables as Record<string, {name: string; module: string; parent_class?: string; kind: string}>).map(([id, info]) => ({
            id,
            label: info.parent_class ? `${info.parent_class}.${info.name}` : info.name,
            layer: info.kind === "function" ? "services" : info.kind === "method" ? "services" : "other",
            color: info.kind === "function" ? "#7c4dff" : info.kind === "method" ? "#448aff" : "#616161",
            entityCount: 1,
            language: "python",
          }));
          const callGraphEdges: GraphEdge[] = [];
          for (const [src, targets] of Object.entries((cg.forward || {}) as Record<string, string[]>)) {
            for (const tgt of targets) {
              callGraphEdges.push({ source: src, target: tgt, type: "calls" });
            }
          }
          data = { nodes: callGraphNodes, edges: callGraphEdges };
        } else {
          // Module-level graph
          // 1) Desktop mode: read analysis.json directly from local filesystem via Tauri
          if (repoPath && "__TAURI__" in window) {
            try {
              const { invoke } = await import("@tauri-apps/api/core");
              const raw = await invoke<string>("read_file_content", {
                repoPath,
                filePath: ".code-wiki/analysis.json",
              });
              const parsed = JSON.parse(raw) as AnalysisData;
              if (parsed.modules && Object.keys(parsed.modules).length > 0) {
                data = transformAnalysis(parsed);
              }
            } catch { /* fall through to HTTP */ }
          }

          // 2) Browser dev mode: fetch from backend API
          if (!data) {
            const res = await fetch("/api/graph/data");
            if (!res.ok) throw new Error(`${res.status}`);
            data = await res.json();
          }
        }

        if (cancelled) return;
        if (!data || data.nodes.length === 0) {
          setError(graphMode === "call" ? "暂无函数调用关系" : "暂无分析数据，请先扫描代码仓库");
          setLoading(false);
          return;
        }
        if (graphMode === "module") {
          _cachedGraphData = data;
          _cacheTimestamp = Date.now();
        }
        setGraphData(data);
        setError(null);
        setLoading(false);
      } catch (e: unknown) {
        if (!cancelled) {
          setError(`加载图谱数据失败: ${e instanceof Error ? e.message : "未知错误"}`);
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
      cyRef.current?.destroy();
      cyRef.current = null;
    };
  }, [repoPath, graphMode]);

  // ---- Initialize cytoscape when data is loaded AND container is mounted ----
  useEffect(() => {
    if (!graphData || !containerRef.current) return;
    console.log("[Graph] container ready, building graph");
    buildGraph(graphData);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphData]);

  // ---- Build cytoscape instance ----
  const buildGraph = useCallback((data: GraphData) => {
    console.log("[Graph] buildGraph called, containerRef:", containerRef.current);
    if (!containerRef.current) return;

    console.log("[Graph] creating cytoscape instance...");
    // Destroy previous instance
    cyRef.current?.destroy();

    const cy = cytoscape({
      container: containerRef.current,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            label: "data(label)",
            "text-valign": "bottom",
            "text-halign": "center",
            "font-size": "9px",
            color: "#888",
            "text-max-width": "120px",
            "text-wrap": "ellipsis",
            // Only show labels when zoomed in enough to read them
            "text-opacity": 0,
            width: "mapData(entityCount, 1, 50, 18, 42)",
            height: "mapData(entityCount, 1, 50, 18, 42)",
            "border-width": 1.5,
            "border-color": "#fff",
          },
        },
        {
          // Show labels at zoom ≥ 1.2
          selector: "node.label-visible",
          style: {
            "text-opacity": 1,
          },
        },
        {
          selector: "edge",
          style: {
            width: 1,
            "line-color": "#ccc",
            "target-arrow-color": "#ccc",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            "arrow-scale": 0.6,
            opacity: 0.5,
          },
        },
        {
          selector: "node:selected",
          style: {
            "border-color": "#f59e0b",
            "border-width": 3,
            "text-opacity": 1,
          },
        },
        {
          selector: "node.highlighted",
          style: {
            "border-color": "#3b82f6",
            "border-width": 2.5,
            opacity: 1,
            "text-opacity": 1,
          },
        },
        {
          selector: "node.dimmed",
          style: { opacity: 0.15, "text-opacity": 0 },
        },
        {
          selector: "edge.dimmed",
          style: { opacity: 0.05 },
        },
      ],
      elements: [
        ...data.nodes.map((n) => ({
          data: { ...n },
        })),
        ...data.edges.map((e) => ({
          data: { source: e.source, target: e.target, type: e.type },
        })),
      ],
      // Use preset positions from cose to avoid double-layout
      layout: { name: "preset" },
      minZoom: 0.08,
      maxZoom: 4,
      // Performance: skip texture for tiny nodes
      textureOnViewport: true,
      pixelRatio: "auto",
    });

    // After creation, attach zoom-based label toggle + run initial layout
    const updateLabels = () => {
      const z = cy.zoom();
      if (z >= 1.2) {
        cy.nodes().addClass("label-visible");
      } else {
        cy.nodes().removeClass("label-visible");
      }
    };
    cy.on("zoom", updateLabels);
    // Initial label state
    updateLabels();

    // Click → select node
    cy.on("tap", "node", (evt) => {
      const node = evt.target;
      setSelectedNode(node.data() as GraphNode);
    });

    cy.on("tap", (evt) => {
      if (evt.target === cy) setSelectedNode(null);
    });

    cyRef.current = cy;
    console.log("[Graph] cytoscape instance created, nodes:", data.nodes.length, "edges:", data.edges.length);

    // Run initial layout (cose for force-directed, works for any graph size)
    runLayout(cy, "cose");
  }, []);

  // ---- Layout runner ----
  const runLayout = useCallback((cy: Core, name: LayoutName) => {
    // Stop any running layout first
    cy.stop();
    cy.layout({
      name,
      animate: true,
      animationDuration: 400,
      // cose: better convergence for large graphs
      ...(name === "cose"
        ? {
            nodeRepulsion: () => 4000,
            idealEdgeLength: () => 60,
            numIter: 1000,
            coolingFactor: 0.95,
            animate: true,
            randomize: true,
          }
        : {}),
      ...(name === "breadthfirst" ? { directed: true, spacingFactor: 1.2, animate: true } : {}),
      ...(name === "concentric"
        ? {
            concentric: (n: { data: (k: string) => unknown }) => {
              const layer = n.data("layer") as string;
              const order = ["routes", "services", "models", "frontend", "config", "other"];
              return order.indexOf(layer);
            },
            minNodeSpacing: 60,
            animate: true,
          }
        : {}),
      ...(name === "circle" ? { animate: true } : {}),
      ...(name === "grid" ? { animate: true, rows: undefined } : {}),
    }).run();
  }, []);

  const changeLayout = useCallback(
    (name: LayoutName) => {
      setLayout(name);
      if (cyRef.current) runLayout(cyRef.current, name);
    },
    [runLayout]
  );

  // ---- Search filter (debounced) ----
  const searchTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const applySearch = useCallback(
    (query: string) => {
      setSearch(query);
      // Debounce: only run filter 150ms after last keystroke
      if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
      searchTimerRef.current = setTimeout(() => {
        const cy = cyRef.current;
        if (!cy) return;

        const q = query.trim().toLowerCase();
        if (!q) {
          cy.nodes().removeClass("highlighted dimmed");
          cy.edges().removeClass("dimmed");
          return;
        }

        // Batch DOM updates for performance
        cy.batch(() => {
          const matched = cy.nodes().filter((n) => {
            const label = ((n.data("label") as string) || "").toLowerCase();
            return label.includes(q);
          });

          cy.nodes().addClass("dimmed");
          cy.edges().addClass("dimmed");
          matched.removeClass("dimmed").addClass("highlighted");
          matched.connectedEdges().removeClass("dimmed");
        });
      }, 150);
    },
    []
  );

  // Cleanup search timer on unmount
  useEffect(() => {
    return () => {
      if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    };
  }, []);

  // ---- Controls ----
  const zoomIn = () => cyRef.current?.zoom(cyRef.current.zoom() * 1.3);
  const zoomOut = () => cyRef.current?.zoom(cyRef.current.zoom() * 0.7);
  const fit = () => cyRef.current?.fit(undefined, 30);

  // ---- No config: don't render — user must configure repo path first ----
  if (!repoPath) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground">
        <div className="text-center">
          <p className="text-2xl mb-2">🗺️</p>
          <p className="text-sm">请先在分析模块配置仓库路径</p>
        </div>
      </div>
    );
  }

  // ---- Loading / empty / error states ----
  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
        加载知识图谱...
      </div>
    );
  }
  if (error) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
        {error}
      </div>
    );
  }

  return (
    <div className="h-full min-h-0 flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-2 p-2 border-b border-border shrink-0 flex-wrap">
        {/* Layout selector */}
        {LAYOUTS.map((l) => (
          <button
            key={l.id}
            onClick={() => changeLayout(l.id)}
            className={`px-2 py-1 text-[11px] rounded transition-colors
              ${layout === l.id ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}
          >
            {l.label}
          </button>
        ))}

        <div className="w-px h-5 bg-border mx-1" />

        {/* Graph mode: module / call */}
        <button
          onClick={() => setGraphMode(graphMode === "module" ? "call" : "module")}
          className={`flex items-center gap-1 px-2 py-1 text-[11px] rounded transition-colors ${
            graphMode === "call" ? "bg-primary text-primary-foreground" : "hover:bg-accent"
          }`}
          title={graphMode === "module" ? "切换到函数调用图" : "切换到模块依赖图"}
        >
          {graphMode === "module" ? <Box size={12} /> : <GitBranch size={12} />}
          {graphMode === "module" ? "模块" : "调用"}
        </button>

        <div className="w-px h-5 bg-border mx-1" />

        {/* Zoom */}
        <button onClick={zoomIn} className="p-1 rounded hover:bg-accent" title="放大">
          <ZoomIn size={14} />
        </button>
        <button onClick={zoomOut} className="p-1 rounded hover:bg-accent" title="缩小">
          <ZoomOut size={14} />
        </button>
        <button onClick={fit} className="p-1 rounded hover:bg-accent" title="适应屏幕">
          <Maximize size={14} />
        </button>

        <div className="w-px h-5 bg-border mx-1" />

        {/* Search */}
        <div className="relative">
          <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={search}
            onChange={(e) => applySearch(e.target.value)}
            placeholder="搜索模块..."
            className="w-36 pl-6 pr-2 py-1 text-[11px] rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>

        {/* Legend */}
        <div className="ml-auto flex items-center gap-2 text-[10px] text-muted-foreground">
          {(["routes", "services", "models", "frontend", "other"] as const).map(
            (layer) => {
              const colors: Record<string, string> = {
                routes: "#0288d1",
                services: "#388e3c",
                models: "#f57c00",
                frontend: "#7b1fa2",
                other: "#616161",
              };
              const labels: Record<string, string> = {
                routes: "路由",
                services: "服务",
                models: "模型",
                frontend: "前端",
                other: "其他",
              };
              return (
                <span key={layer} className="flex items-center gap-1">
                  <span
                    className="inline-block w-2 h-2 rounded-full"
                    style={{ backgroundColor: colors[layer] }}
                  />
                  {labels[layer]}
                </span>
              );
            }
          )}
        </div>
      </div>

      {/* Canvas */}
      <div className="flex-1 min-h-0 relative">
        <div ref={containerRef} style={{ width: "100%", height: "100%" }} />

        {/* Selected node info */}
        {selectedNode && (
          <div className="absolute bottom-3 left-3 right-3 bg-card/95 border border-border rounded-lg p-3 text-xs shadow-lg backdrop-blur-sm max-w-sm">
            <div className="flex items-center gap-2 mb-1">
              <span
                className="inline-block w-3 h-3 rounded-full shrink-0"
                style={{ backgroundColor: selectedNode.color }}
              />
              <span className="font-mono font-medium truncate">{selectedNode.label}</span>
            </div>
            <div className="text-muted-foreground flex gap-3">
              <span>层: {selectedNode.layer}</span>
              <span>实体: {selectedNode.entityCount}</span>
              <span>语言: {selectedNode.language}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
