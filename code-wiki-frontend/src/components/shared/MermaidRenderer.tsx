import { useEffect, useRef, useState, memo } from "react";
import mermaid from "mermaid";

// Initialize mermaid
mermaid.initialize({
  startOnLoad: false,
  theme: "default",
  securityLevel: "strict",
  maxTextSize: 200_000,
  maxEdges: 500,
  fontFamily: '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "WenQuanYi Micro Hei", system-ui, sans-serif',
});

interface MermaidRendererProps {
  chart: string;
  className?: string;
}

// Simple string hash for stable DOM ids
function hashStr(s: string): string {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  }
  return (h >>> 0).toString(36);
}

// Global SVG cache — survives component unmounts
const svgCache = new Map<string, string>();
let _renderSeq = 0;

export const MermaidRenderer = memo(function MermaidRenderer({ chart, className }: MermaidRendererProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [svg, setSvg] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const cacheCleared = useRef(false);

  // Clear stale cache once on first mount (fixes stale CJK-font SVGs after config change)
  useEffect(() => {
    if (!cacheCleared.current) {
      cacheCleared.current = true;
      svgCache.clear();
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      const trimmed = chart.trim();
      if (!trimmed) return;

      // Check cache first
      const cached = svgCache.get(trimmed);
      if (cached !== undefined) {
        if (!cancelled) {
          setSvg(cached);
          setError(null);
          setLoading(false);
        }
        return;
      }

      if (!cancelled) setLoading(true);

      try {
        // Unique id per render (avoids DOM clash with multiple instances)
        const id = `mermaid-${hashStr(trimmed)}-${_renderSeq++}`;
        const { svg: result } = await mermaid.render(id, trimmed);
        // Store in cache
        svgCache.set(trimmed, result);
        if (!cancelled) {
          setSvg(result);
          setError(null);
          setLoading(false);
        }
      } catch (e) {
        if (!cancelled) {
          setError(String(e));
          setSvg("");
          setLoading(false);
        }
      }
    }

    render();

    return () => { cancelled = true; };
  }, [chart]);

  if (loading && !svg && !error) {
    return (
      <div className={`mermaid-container ${className || ""} animate-pulse`}>
        <div className="flex items-center justify-center p-8">
          <div className="w-8 h-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 border border-destructive/30 rounded bg-destructive/5">
        <p className="text-xs text-destructive font-medium mb-1">图表渲染失败</p>
        <pre className="text-[10px] text-muted-foreground whitespace-pre-wrap">
          {error}
        </pre>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={`mermaid-container ${className || ""}`}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
});
