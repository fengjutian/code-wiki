import { useState } from "react";

export function ImpactPanel() {
  const [file, setFile] = useState("");
  const [report, setReport] = useState<{
    risk_score: number; summary: string;
    changed_functions: string[];
    affected_production: Array<{name: string; module: string; distance: number}>;
    affected_tests: Array<{name: string; module: string; distance: number}>;
  } | null>(null);
  const [loading, setLoading] = useState(false);

  const analyze = async () => {
    if (!file.trim()) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/metrics/impact?changed_files=${encodeURIComponent(file)}`);
      if (res.ok) setReport(await res.json());
    } catch { /* */ }
    setLoading(false);
  };

  return (
    <div className="h-full min-h-0 overflow-y-auto p-6">
      <h2 className="text-lg font-semibold mb-6">变更影响分析</h2>

      <div className="flex gap-2 mb-6">
        <input value={file} onChange={e => setFile(e.target.value)}
          onKeyDown={e => e.key === "Enter" && analyze()}
          placeholder="文件路径，多个用逗号分隔 如 services/auth.py,models/user.py"
          className="flex-1 px-3 py-1.5 text-sm rounded border border-input bg-background" />
        <button onClick={analyze} disabled={loading}
          className="px-4 py-1.5 text-sm rounded bg-primary text-primary-foreground disabled:opacity-50">
          {loading ? "分析中..." : "分析影响"}
        </button>
      </div>

      {report && (
        <div className="space-y-4">
          {/* Risk score */}
          <div className="p-4 rounded-lg bg-card border border-border text-center">
            <p className="text-xs text-muted-foreground">变更风险评分</p>
            <p className={`text-4xl font-bold ${
              report.risk_score >= 0.7 ? "text-red-500" :
              report.risk_score >= 0.4 ? "text-yellow-500" : "text-green-500"
            }`}>{Math.round(report.risk_score * 100)}%</p>
            <p className="text-xs text-muted-foreground mt-1">{report.summary}</p>
          </div>

          {/* Changed functions */}
          {report.changed_functions.length > 0 && (
            <div className="p-3 rounded-lg bg-card border border-border">
              <h3 className="text-sm font-medium mb-2">变更的函数 ({report.changed_functions.length})</h3>
              <div className="flex flex-wrap gap-1">
                {report.changed_functions.map((f, i) => (
                  <code key={i} className="px-2 py-0.5 text-[10px] bg-secondary rounded">{f.split("::").pop()}</code>
                ))}
              </div>
            </div>
          )}

          {/* Affected production */}
          {report.affected_production.length > 0 && (
            <div className="p-3 rounded-lg bg-card border border-border">
              <h3 className="text-sm font-medium mb-2">受影响的生产代码 ({report.affected_production.length})</h3>
              <div className="space-y-1">
                {report.affected_production.map((a, i) => (
                  <div key={i} className="flex items-center gap-2 p-1.5 rounded bg-secondary/50 text-xs">
                    <span className="text-[10px] text-muted-foreground shrink-0">距离 {a.distance}</span>
                    <code className="font-mono truncate">{a.module}</code>
                    <span className="text-muted-foreground">→</span>
                    <code className="font-mono">{a.name}</code>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Affected tests */}
          {report.affected_tests.length > 0 && (
            <div className="p-3 rounded-lg bg-card border border-border">
              <h3 className="text-sm font-medium mb-2">受影响的测试 ({report.affected_tests.length})</h3>
              <div className="space-y-1">
                {report.affected_tests.map((a, i) => (
                  <div key={i} className="flex items-center gap-2 p-1.5 rounded bg-secondary/50 text-xs">
                    <span className="text-[10px] text-muted-foreground shrink-0">距离 {a.distance}</span>
                    <code className="font-mono truncate">{a.module}</code>
                    <span className="text-muted-foreground">→</span>
                    <code className="font-mono">{a.name}</code>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {!report && !loading && (
        <div className="text-sm text-muted-foreground mt-12 text-center">
          <p>输入文件路径，分析代码变更的影响范围</p>
          <p className="text-xs mt-1">基于调用图自动计算受影响的上下游函数和测试</p>
        </div>
      )}
    </div>
  );
}
