import { useState } from "react";
import { MermaidRenderer } from "@/components/shared/MermaidRenderer";

export function ICFGPanel() {
  const [func, setFunc] = useState("");
  const [file, setFile] = useState("");
  const [icfg, setIcfg] = useState<{
    function_name: string;
    file: string;
    callers_count: number;
    callees_count: number;
    total_callables: number;
    total_edges: number;
    callers: string[];
    callees: string[];
    mermaid: string;
  } | null>(null);
  const [error, setError] = useState("");

  const load = async () => {
    if (!func.trim()) return;
    setError("");
    try {
      const params = new URLSearchParams({ function: func });
      if (file.trim()) params.set("file", file.trim());
      const res = await fetch(`/api/metrics/icfg?${params}`);
      const data = await res.json();
      if (data.error) { setError(data.error); setIcfg(null); }
      else setIcfg(data);
    } catch { setError("请求失败"); }
  };

  return (
    <div className="h-full min-h-0 overflow-y-auto p-6">
      <h2 className="text-lg font-semibold mb-6">过程间控制流图 ICFG</h2>
      <p className="text-xs text-muted-foreground mb-4">
        基于调用图展示函数的跨过程控制流 — 调用者 → 目标函数 → 被调用者
      </p>

      <div className="flex gap-2 mb-4">
        <input value={func} onChange={e => setFunc(e.target.value)}
          placeholder="函数名，如 nanopore_assembly_info"
          onKeyDown={e => e.key === "Enter" && load()}
          className="flex-1 px-3 py-1.5 text-sm rounded border border-input bg-background" />
        <input value={file} onChange={e => setFile(e.target.value)}
          placeholder="可选：文件路径"
          className="w-56 px-3 py-1.5 text-sm rounded border border-input bg-background" />
        <button onClick={load} className="px-4 py-1.5 text-sm rounded bg-primary text-primary-foreground">生成 ICFG</button>
      </div>

      {error && <p className="text-sm text-red-500 mb-4">{error}</p>}

      {icfg && (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-3">
            <Card label="目标函数" value={icfg.function_name} />
            <Card label="调用者" value={icfg.callers_count} />
            <Card label="被调用者" value={icfg.callees_count} />
            <Card label="全图规模" value={`${icfg.total_callables} 函数 / ${icfg.total_edges} 边`} />
          </div>

          {(icfg.callers.length > 0 || icfg.callees.length > 0) && (
            <div className="grid grid-cols-2 gap-4">
              {icfg.callers.length > 0 && (
                <div className="p-3 rounded-lg bg-card border border-border text-xs">
                  <p className="font-medium mb-1 text-blue-400">← 调用者 (callers)</p>
                  <ul className="space-y-0.5 text-muted-foreground">
                    {icfg.callers.map((c, i) => <li key={i}>{c}</li>)}
                  </ul>
                </div>
              )}
              {icfg.callees.length > 0 && (
                <div className="p-3 rounded-lg bg-card border border-border text-xs">
                  <p className="font-medium mb-1 text-green-400">→ 被调用者 (callees)</p>
                  <ul className="space-y-0.5 text-muted-foreground">
                    {icfg.callees.map((c, i) => <li key={i}>{c}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}

          <div className="p-4 rounded-lg bg-card border border-border">
            <h3 className="text-sm font-medium mb-2">过程间控制流图</h3>
            <MermaidRenderer chart={icfg.mermaid} className="max-h-[500px]" />
          </div>
        </div>
      )}

      {!icfg && !error && (
        <div className="text-sm text-muted-foreground mt-12 text-center">
          <p>输入函数名，生成跨过程的控制流图</p>
          <p className="text-xs mt-1">需要先运行全量分析以构建调用图</p>
        </div>
      )}
    </div>
  );
}

function Card({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="p-3 rounded-lg bg-card border border-border text-center">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="text-lg font-bold font-mono truncate">{value}</p>
    </div>
  );
}
