import { useState, useEffect, useCallback } from "react";
import { ActivityIcon, CheckCircleIcon, XCircleIcon, RefreshCwIcon } from "lucide-react";

interface HealthResponse {
  status: string;
  service: string;
  version: string;
  models: {
    configured_model: string;
    base_url: string;
    temperature: number;
    has_api_key: boolean;
  };
  config: {
    repo_path: string;
    languages: string[];
    theme: string;
  };
}

export function TestPanel() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const checkHealth = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/health");
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      const data: HealthResponse = await res.json();
      setHealth(data);
    } catch (e) {
      setError(String(e));
      setHealth(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    checkHealth();
  }, [checkHealth]);

  const isOk = health?.status === "ok";

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-xl font-semibold">服务状态</h1>
          <button
            onClick={checkHealth}
            disabled={loading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm bg-secondary hover:bg-accent transition-colors disabled:opacity-50"
          >
            <RefreshCwIcon size={14} className={loading ? "animate-spin" : ""} />
            刷新
          </button>
        </div>

        {/* Overall Status */}
        <div className="mb-6 p-4 rounded-xl border border-border bg-card">
          <div className="flex items-center gap-3">
            {loading ? (
              <RefreshCwIcon size={28} className="animate-spin text-muted-foreground" />
            ) : isOk ? (
              <CheckCircleIcon size={28} className="text-green-500" />
            ) : (
              <XCircleIcon size={28} className="text-red-500" />
            )}
            <div>
              <div className="text-lg font-medium">
                {loading ? "检测中..." : isOk ? "服务运行正常" : error ? "服务不可达" : "未知状态"}
              </div>
              {health && (
                <div className="text-sm text-muted-foreground">
                  {health.service} v{health.version}
                </div>
              )}
            </div>
          </div>
          {error && (
            <div className="mt-2 text-sm text-red-500 bg-red-50 dark:bg-red-950/20 rounded-lg p-2">
              {error}
            </div>
          )}
        </div>

        {/* Model Info */}
        {health && (
          <>
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">
              模型配置
            </h2>
            <div className="mb-6 p-4 rounded-xl border border-border bg-card space-y-3">
              <InfoRow label="使用模型" value={health.models.configured_model} />
              <InfoRow label="API 地址" value={health.models.base_url || "未配置"} />
              <InfoRow label="温度参数" value={String(health.models.temperature)} />
              <InfoRow
                label="API Key"
                value={health.models.has_api_key ? "✅ 已配置" : "❌ 未配置"}
              />
            </div>

            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">
              基础配置
            </h2>
            <div className="p-4 rounded-xl border border-border bg-card space-y-3">
              <InfoRow label="仓库路径" value={health.config.repo_path || "未设置"} />
              <InfoRow label="支持语言" value={health.config.languages.join(", ")} />
              <InfoRow label="主题" value={health.config.theme} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium font-mono text-xs">{value}</span>
    </div>
  );
}
