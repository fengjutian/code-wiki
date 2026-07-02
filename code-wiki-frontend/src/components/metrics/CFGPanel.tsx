import { useState } from "react";

export function CFGPanel() {
  const [file, setFile] = useState("");
  const [func, setFunc] = useState("");
  const [cfg, setCfg] = useState<{function_name: string; cyclomatic_complexity: number; blocks_count: number; nesting_depth: number; mermaid: string} | null>(null);
  const [error, setError] = useState("");

  const load = async () => {
    if (!file.trim() || !func.trim()) return;
    setError("");
    try {
      const res = await fetch(`/api/metrics/cfg?file=${encodeURIComponent(file)}&function=${encodeURIComponent(func)}`);
      const data = await res.json();
      if (data.error) { setError(data.error); setCfg(null); }
      else setCfg(data);
    } catch { setError("请求失败"); }
  };

  return (
    <div className="h-full min-h-0 overflow-y-auto p-6">
      <h2 className="text-lg font-semibold mb-6">控制流图 CFG</h2>

      <div className="flex gap-2 mb-4">
        <input value={file} onChange={e => setFile(e.target.value)}
          placeholder="文件路径，如 services/auth.py"
          className="flex-1 px-3 py-1.5 text-sm rounded border border-input bg-background" />
        <input value={func} onChange={e => setFunc(e.target.value)}
          placeholder="函数名"
          onKeyDown={e => e.key === "Enter" && load()}
          className="w-40 px-3 py-1.5 text-sm rounded border border-input bg-background" />
        <button onClick={load} className="px-4 py-1.5 text-sm rounded bg-primary text-primary-foreground">生成 CFG</button>
      </div>

      {error && <p className="text-sm text-red-500 mb-4">{error}</p>}

      {cfg && (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-3">
            <Card label="函数名" value={cfg.function_name} />
            <Card label="圈复杂度" value={cfg.cyclomatic_complexity} />
            <Card label="基本块" value={cfg.blocks_count} />
            <Card label="嵌套深度" value={cfg.nesting_depth} />
          </div>
          <div className="p-4 rounded-lg bg-card border border-border">
            <h3 className="text-sm font-medium mb-2">Mermaid 图</h3>
            <pre className="text-[11px] bg-secondary rounded p-3 overflow-x-auto max-h-96 whitespace-pre-wrap font-mono">{cfg.mermaid}</pre>
          </div>
        </div>
      )}

      {!cfg && !error && (
        <div className="text-sm text-muted-foreground mt-12 text-center">
          <p>输入文件路径和函数名，生成控制流图</p>
          <p className="text-xs mt-1">例如: 文件=services/auth.py, 函数=authenticate</p>
        </div>
      )}
    </div>
  );
}

function Card({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="p-3 rounded-lg bg-card border border-border text-center">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="text-xl font-bold font-mono">{value}</p>
    </div>
  );
}
