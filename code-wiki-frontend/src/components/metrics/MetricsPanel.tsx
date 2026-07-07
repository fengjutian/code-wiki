import { useEffect, useState, useCallback } from "react";
import { RefreshCw, AlertTriangle, Code2, GitBranch, Shield } from "lucide-react";

interface HealthData {
  total_modules?: number;
  total_functions?: number;
  total_classes?: number;
  total_lines?: number;
  avg_cyclomatic_complexity?: number;
  max_cyclomatic_complexity?: number;
  avg_coupling?: number;
  max_coupling?: number;
  isolated_modules?: number;
  test_coverage?: number;
  health_score?: number;
  hotspots?: { file: string; risk_score: number; reasons: string[] }[];
  complex_functions?: [string, number][];
  language_breakdown?: Record<string, number>;
  docstring_coverage?: number;
  external_deps?: number;
  total_imports?: number;
}

export function MetricsPanel() {
  const [data, setData] = useState<HealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchMetrics = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/metrics/health");
      if (!res.ok) throw new Error(`${res.status}`);
      const json = await res.json();
      setData(json);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMetrics();
  }, [fetchMetrics]);

  const scoreColor = data?.health_score == null
    ? "text-muted-foreground"
    : (data.health_score >= 80
    ? "text-green-500" : (data.health_score >= 50
    ? "text-yellow-500" : "text-red-500"));

  const scoreDisplay = data?.health_score == null ? "--" : data.health_score;

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
        加载指标数据...
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3 text-muted-foreground">
        <p className="text-sm">无法加载指标: {error}</p>
        <p className="text-xs">请先运行代码分析</p>
        <button onClick={fetchMetrics} className="px-3 py-1 text-xs rounded bg-primary text-primary-foreground">
          重试
        </button>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="h-full min-h-0 overflow-y-auto p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-lg font-semibold">项目健康度仪表盘</h2>
        <button onClick={fetchMetrics} className="flex items-center gap-1 px-2 py-1 text-xs rounded hover:bg-accent" title="刷新">
          <RefreshCw size={14} /> 刷新
        </button>
      </div>

      {/* Health Score */}
      <div className="mb-8 p-6 rounded-xl bg-card border border-border text-center">
        <p className="text-sm text-muted-foreground mb-2">综合健康评分</p>
        <p className={`text-5xl font-bold ${scoreColor}`}>{scoreDisplay}</p>
        <p className="text-xs text-muted-foreground mt-1">
          {data?.health_score == null ? "请先运行分析" : "满分 100"}
        </p>
      </div>

      {/* Key Metrics Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <MetricCard icon={<Code2 size={18} />} label="模块数" value={data.total_modules ?? 0} />
        <MetricCard icon={<GitBranch size={18} />} label="函数数" value={data.total_functions ?? 0} />
        <MetricCard icon={<Shield size={18} />} label="覆盖率" value={`${Math.round((data.test_coverage ?? 0) * 100)}%`} />
        <MetricCard icon={<AlertTriangle size={18} />} label="圈复杂度(平均)" value={(data.avg_cyclomatic_complexity ?? 0).toFixed(1)} />
      </div>

      {/* Second Metrics Row: Quality & Scale */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <MetricCard icon={<span className="text-lg">📄</span>} label="文档覆盖率" value={`${Math.round((data.docstring_coverage ?? 0) * 100)}%`} />
        <MetricCard icon={<span className="text-lg">📦</span>} label="外部依赖" value={data.external_deps ?? 0} />
        <MetricCard icon={<span className="text-lg">🔗</span>} label="内部导入" value={data.total_imports ?? 0} />
        <MetricCard icon={<span className="text-lg">📝</span>} label="总行数" value={data.total_lines ?? 0} />
      </div>

      {/* Language Breakdown */}
      {data.language_breakdown && Object.keys(data.language_breakdown).length > 0 && (
        <div className="mb-8 p-4 rounded-lg bg-card border border-border">
          <h3 className="text-sm font-medium mb-3">语言分布</h3>
          <div className="flex flex-wrap gap-3">
            {Object.entries(data.language_breakdown).map(([lang, count]) => (
              <span key={lang} className="px-3 py-1.5 rounded-full bg-accent text-xs font-mono">
                {lang}: <strong>{count}</strong>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Complexity & Coupling */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        <div className="p-4 rounded-lg bg-card border border-border">
          <h3 className="text-sm font-medium mb-3">复杂度</h3>
          <div className="space-y-2 text-xs">
            <Row label="平均圈复杂度" value={data.avg_cyclomatic_complexity?.toFixed(1) ?? "-"} />
            <Row label="最大圈复杂度" value={data.max_cyclomatic_complexity ?? "-"} />
          </div>
        </div>
        <div className="p-4 rounded-lg bg-card border border-border">
          <h3 className="text-sm font-medium mb-3">耦合度</h3>
          <div className="space-y-2 text-xs">
            <Row label="平均耦合度" value={data.avg_coupling?.toFixed(1) ?? "-"} />
            <Row label="最大耦合度" value={data.max_coupling ?? "-"} />
            <Row label="总类数" value={data.total_classes ?? 0} />
            <Row label="孤立模块" value={data.isolated_modules ?? 0} />
          </div>
        </div>
      </div>

      {/* Risk Hotspots */}
      {(data.hotspots ?? []).length > 0 && (
        <div className="mb-8">
          <h3 className="text-sm font-medium mb-3 flex items-center gap-2">
            <AlertTriangle size={16} className="text-yellow-500" />
            风险热点 (Top {data.hotspots!.length})
          </h3>
          <div className="space-y-2">
            {data.hotspots!.map((h, i) => (
              <div key={i} className="flex items-center justify-between p-2 rounded bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-900 text-xs">
                <code className="font-mono">{h.file}</code>
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground">{h.reasons.join(", ")}</span>
                  <span className="font-bold text-red-600">风险: {Math.round(h.risk_score * 100)}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* High Complexity Functions */}
      {(data.complex_functions ?? []).length > 0 && (
        <div>
          <h3 className="text-sm font-medium mb-3">高复杂度函数 (Top 10)</h3>
          <div className="space-y-1">
            {data.complex_functions!.map(([name, cc], i) => (
              <div key={i} className="flex items-center justify-between p-2 rounded bg-card border border-border text-xs">
                <code className="font-mono truncate max-w-[300px]">{name}</code>
                <span className={cc > 20 ? "text-red-500 font-bold" : cc > 10 ? "text-yellow-500" : "text-muted-foreground"}>
                  圈复杂度: {cc}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Taint Analysis */}
      <TaintSection />
    </div>
  );
}

function MetricCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: string | number }) {
  return (
    <div className="p-4 rounded-lg bg-card border border-border text-center">
      <div className="flex justify-center mb-2 text-muted-foreground">{icon}</div>
      <p className="text-2xl font-bold">{value}</p>
      <p className="text-[10px] text-muted-foreground mt-1">{label}</p>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono font-medium">{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-panels
// ---------------------------------------------------------------------------

function TaintSection() {
  const [flows, setFlows] = useState<Array<{source: string; sink: string; risk_level: string}>>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const res = await fetch("/api/metrics/taint");
        if (res.ok) {
          const data = await res.json();
          setFlows(data.flows || []);
        }
      } catch { /* */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return <Section title="污点分析" content={<p className="text-xs text-muted-foreground">加载中...</p>} />;
  if (flows.length === 0) return null;

  return (
    <Section title={`污点分析 (${flows.length} 条)`} content={
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {flows.slice(0, 20).map((f, i) => (
          <div key={i} className={`flex items-center gap-2 p-1.5 rounded text-xs ${
            f.risk_level === "high" ? "bg-red-50 dark:bg-red-950/20" :
            f.risk_level === "medium" ? "bg-yellow-50 dark:bg-yellow-950/20" :
            "bg-green-50 dark:bg-green-950/20"
          }`}>
            <span className="shrink-0">{f.risk_level === "high" ? "🔴" : f.risk_level === "medium" ? "🟡" : "🟢"}</span>
            <code className="font-mono truncate">{f.source}</code>
            <span className="text-muted-foreground">→</span>
            <code className="font-mono truncate">{f.sink}</code>
          </div>
        ))}
      </div>
    } />
  );
}

function Section({ title, content }: { title: string; content: React.ReactNode }) {
  return (
    <div className="mb-6">
      <h3 className="text-sm font-medium mb-3">{title}</h3>
      <div className="p-3 rounded-lg bg-card border border-border">{content}</div>
    </div>
  );
}
