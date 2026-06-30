import { useEffect, useRef, useState, useCallback } from "react";
import cytoscape, { type Core } from "cytoscape";
import { useConfigStore } from "@/store/configStore";
import { Search, ZoomIn, ZoomOut, Maximize } from "lucide-react";

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

export function KnowledgeGraph() {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [layout, setLayout] = useState<LayoutName>("cose");
  const [search, setSearch] = useState("");
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // ---- Fetch data ----
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/graph/data");
        if (!res.ok) throw new Error(`${res.status}`);
        const data: GraphData = await res.json();
        if (cancelled) return;
        if (data.nodes.length === 0) {
          setError("暂无分析数据，请先扫描代码仓库");
          setLoading(false);
          return;
        }
        buildGraph(data);
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
  }, []);

  // ---- Build cytoscape instance ----
  const buildGraph = useCallback((data: GraphData) => {
    if (!containerRef.current) return;

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
            width: "mapData(entityCount, 1, 50, 18, 42)",
            height: "mapData(entityCount, 1, 50, 18, 42)",
            "border-width": 1.5,
            "border-color": "#fff",
            "transition-property": "width, height",
            "transition-duration": 200,
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
          },
        },
        {
          selector: "node.highlighted",
          style: {
            "border-color": "#3b82f6",
            "border-width": 2.5,
            opacity: 1,
          },
        },
        {
          selector: "node.dimmed",
          style: { opacity: 0.15 },
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
      layout: { name: "cose", animate: false },
      wheelSensitivity: 0.3,
      minZoom: 0.1,
      maxZoom: 3,
    });

    // Click → select node
    cy.on("tap", "node", (evt) => {
      const node = evt.target;
      setSelectedNode(node.data() as GraphNode);
    });

    cy.on("tap", (evt) => {
      if (evt.target === cy) setSelectedNode(null);
    });

    cyRef.current = cy;

    // Apply initial layout
    runLayout(cy, layout);
  }, [layout]);

  // ---- Layout runner ----
  const runLayout = useCallback((cy: Core, name: LayoutName) => {
    cy.layout({
      name,
      animate: true,
      animationDuration: 600,
      ...(name === "cose" ? { nodeRepulsion: 6000, idealEdgeLength: 80 } : {}),
      ...(name === "breadthfirst" ? { directed: true, spacingFactor: 1.2 } : {}),
      ...(name === "concentric"
        ? {
            concentric: (n: { data: (k: string) => unknown }) => {
              const layer = n.data("layer") as string;
              const order = ["routes", "services", "models", "frontend", "config", "other"];
              return order.indexOf(layer);
            },
            minNodeSpacing: 60,
          }
        : {}),
    }).run();
  }, []);

  const changeLayout = useCallback(
    (name: LayoutName) => {
      setLayout(name);
      if (cyRef.current) runLayout(cyRef.current, name);
    },
    [runLayout]
  );

  // ---- Search filter ----
  const applySearch = useCallback(
    (query: string) => {
      setSearch(query);
      const cy = cyRef.current;
      if (!cy) return;

      const q = query.trim().toLowerCase();
      if (!q) {
        cy.nodes().removeClass("highlighted dimmed");
        cy.edges().removeClass("dimmed");
        return;
      }

      const matched = cy.nodes().filter((n) => {
        const label = ((n.data("label") as string) || "").toLowerCase();
        return label.includes(q);
      });

      cy.nodes().addClass("dimmed");
      cy.edges().addClass("dimmed");
      matched.removeClass("dimmed").addClass("highlighted");

      // Also show edges connected to matched nodes
      matched.connectedEdges().removeClass("dimmed");
    },
    []
  );

  // ---- Controls ----
  const zoomIn = () => cyRef.current?.zoom(cyRef.current.zoom() * 1.3);
  const zoomOut = () => cyRef.current?.zoom(cyRef.current.zoom() * 0.7);
  const fit = () => cyRef.current?.fit(undefined, 30);

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
    <div className="h-full flex flex-col">
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
      <div className="flex-1 relative">
        <div ref={containerRef} className="absolute inset-0" />

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
