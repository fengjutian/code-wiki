import { useState, useEffect } from "react";
import {
  BookOpenIcon, LayersIcon, MapPinIcon, StarIcon,
  FolderTreeIcon, HashIcon, FootprintsIcon, ArrowRightIcon,
} from "lucide-react";

interface TourStep {
  step: number;
  depth: number;
  path: string;
  layer: string;
  entity_count: number;
  classes: number;
  functions: number;
  language: string;
  dependencies: string[];
  dependents_count: number;
  description: string;
}

interface TourData {
  status: string;
  message?: string;
  entry_points?: string[];
  total_steps?: number;
  total_entities_covered?: number;
  max_depth?: number;
  steps?: TourStep[];
}

interface GuideData {
  status: string;
  message?: string;
  overview?: {
    analyzed_at: string;
    total_files: number;
    total_classes: number;
    total_functions: number;
    total_interfaces: number;
    total_components: number;
    total_entities: number;
    languages: Record<string, number>;
    dependency_edges: number;
    max_dependency_depth: number;
  };
  entry_points?: { path: string; score: number; reasons: string[]; language: string; entity_count: number }[];
  architecture?: { layers: { name: string; file_count: number; top_modules: string[] }[] };
  core_modules?: { path: string; dependents: number; layer: string }[];
  directory_summary?: { name: string; path: string; file_count: number }[];
}

const LAYER_COLORS: Record<string, string> = {
  "接口层": "#0288d1",
  "服务层": "#388e3c",
  "数据层": "#f57c00",
  "工具层": "#7b1fa2",
  "配置/入口": "#c62828",
  "前端": "#e91e63",
  "数据库迁移": "#00838f",
  "测试": "#795548",
  "基础设施": "#546e7a",
};

export function GuidePanel() {
  const [data, setData] = useState<GuideData | null>(null);
  const [tour, setTour] = useState<TourData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [guideRes, tourRes] = await Promise.all([
          fetch("/api/guide"),
          fetch("/api/tour"),
        ]);
        if (!guideRes.ok) throw new Error(`${guideRes.status}`);
        setData(await guideRes.json());
        if (tourRes.ok) setTour(await tourRes.json());
      } catch (e) {
        setError(`加载失败: ${e instanceof Error ? e.message : "未知错误"}`);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
        正在生成上手指南...
      </div>
    );
  }

  if (error || !data || data.status !== "ok") {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground">
        <div className="text-center max-w-md">
          <p className="text-3xl mb-3">📖</p>
          <p className="text-sm">{data?.message || error || "暂无数据"}</p>
        </div>
      </div>
    );
  }

  const o = data.overview!;

  return (
    <div className="h-full overflow-auto">
      <div className="max-w-4xl mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3 pb-4 border-b border-border">
          <BookOpenIcon size={24} className="text-primary" />
          <div>
            <h1 className="text-xl font-semibold">项目上手指南</h1>
            <p className="text-xs text-muted-foreground">
              基于分析结果自动生成 · 分析时间: {o.analyzed_at?.slice(0, 16) || "未知"}
            </p>
          </div>
        </div>

        {/* Section: Guided Tour — learning path */}
        {tour && tour.status === "ok" && tour.steps && tour.steps.length > 0 && (
          <Section icon={<FootprintsIcon size={16} />} title={`学习导览 (${tour.total_steps} 步, 覆盖 ${tour.total_entities_covered} 个实体)`}>
            <div className="space-y-0 border border-border rounded-xl overflow-hidden">
              {tour.steps.map((step, i) => (
                <div
                  key={step.step}
                  className={`flex gap-3 p-3 ${i % 2 === 0 ? "bg-card" : "bg-secondary/30"} ${i < tour.steps!.length - 1 ? "border-b border-border" : ""}`}
                >
                  {/* Step number + depth indicator */}
                  <div className="flex flex-col items-center shrink-0 w-10">
                    <span
                      className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold"
                      style={{
                        backgroundColor: LAYER_COLORS[step.layer] || "#616161",
                        color: "#fff",
                      }}
                    >
                      {step.step}
                    </span>
                    <span className="text-[9px] text-muted-foreground mt-0.5">
                      深度 {step.depth}
                    </span>
                  </div>

                  {/* Step content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <code className="text-xs font-mono text-primary">{step.path}</code>
                      <span
                        className="px-1.5 py-0.5 rounded text-[10px] shrink-0"
                        style={{
                          backgroundColor: (LAYER_COLORS[step.layer] || "#616161") + "20",
                          color: LAYER_COLORS[step.layer] || "#616161",
                        }}
                      >
                        {step.layer}
                      </span>
                      {step.dependents_count >= 10 && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] bg-amber-500/10 text-amber-600 shrink-0">
                          🔥 核心
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                      {step.description}
                    </p>
                    {/* Dependency chain */}
                    {step.dependencies.length > 0 && (
                      <div className="flex items-center gap-1 mt-1.5 text-[10px] text-muted-foreground flex-wrap">
                        <span>↓</span>
                        {step.dependencies.slice(0, 4).map((dep) => (
                          <code key={dep} className="bg-secondary px-1 rounded text-[10px]">{dep}</code>
                        ))}
                        {step.dependencies.length > 4 && (
                          <span>+{step.dependencies.length - 4}</span>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Stats */}
                  <div className="flex flex-col items-end gap-1 shrink-0 text-[10px] text-muted-foreground">
                    <span>{step.classes > 0 && `${step.classes} 类`}</span>
                    <span>{step.functions > 0 && `${step.functions} 函数`}</span>
                  </div>
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* Section: Overview */}
        <Section icon={<HashIcon size={16} />} title="项目概览">
          <div className="grid grid-cols-3 sm:grid-cols-4 gap-3">
            <StatCard label="文件数" value={o.total_files} />
            <StatCard label="类" value={o.total_classes} />
            <StatCard label="函数" value={o.total_functions} />
            <StatCard label="实体总数" value={o.total_entities} />
            <StatCard label="依赖边" value={o.dependency_edges} />
            <StatCard label="最大深度" value={o.max_dependency_depth} />
          </div>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            <span className="text-muted-foreground">语言:</span>
            {Object.entries(o.languages).map(([lang, count]) => (
              <span key={lang} className="px-2 py-0.5 rounded-full bg-secondary text-muted-foreground">
                {lang} ({count})
              </span>
            ))}
          </div>
        </Section>

        {/* Section: Entry Points */}
        <Section icon={<MapPinIcon size={16} />} title="入口文件">
          <div className="space-y-2">
            {data.entry_points?.map((ep) => (
              <div key={ep.path} className="flex items-center justify-between p-2 rounded-lg bg-secondary/50 text-xs">
                <div>
                  <code className="font-mono text-xs">{ep.path}</code>
                  <div className="text-muted-foreground mt-0.5">
                    {ep.reasons.join(" · ")}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-muted-foreground">{ep.language}</span>
                  <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[10px]">
                    {ep.entity_count} 实体
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* Section: Architecture */}
        <Section icon={<LayersIcon size={16} />} title="架构分层">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {data.architecture?.layers.map((layer) => (
              <div
                key={layer.name}
                className="p-3 rounded-lg border border-border"
                style={{ borderLeftColor: LAYER_COLORS[layer.name] || "#616161", borderLeftWidth: 3 }}
              >
                <div className="text-sm font-medium">{layer.name}</div>
                <div className="text-2xl font-bold mt-1">{layer.file_count}</div>
                <div className="text-[10px] text-muted-foreground mt-1">
                  {layer.top_modules.slice(0, 3).join(", ")}
                  {layer.top_modules.length > 3 && ` +${layer.top_modules.length - 3}`}
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* Section: Core Modules */}
        <Section icon={<StarIcon size={16} />} title="核心模块（被依赖最多）">
          <div className="space-y-2">
            {data.core_modules?.map((cm) => (
              <div key={cm.path} className="flex items-center justify-between p-2 rounded-lg bg-secondary/50 text-xs">
                <div className="flex items-center gap-2">
                  <span
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{ backgroundColor: LAYER_COLORS[cm.layer] || "#616161" }}
                  />
                  <code className="font-mono text-xs">{cm.path}</code>
                </div>
                <span className="text-muted-foreground">{cm.dependents} 个依赖方</span>
              </div>
            ))}
          </div>
        </Section>

        {/* Section: Directory Summary */}
        <Section icon={<FolderTreeIcon size={16} />} title="目录结构">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {data.directory_summary?.map((dir) => (
              <div key={dir.path} className="flex items-center gap-2 p-2 rounded-lg border border-border text-xs">
                <FolderTreeIcon size={12} className="text-muted-foreground shrink-0" />
                <span className="font-mono truncate">{dir.name}/</span>
                <span className="text-muted-foreground ml-auto">{dir.file_count}</span>
              </div>
            ))}
          </div>
        </Section>
      </div>
    </div>
  );
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-muted-foreground">{icon}</span>
        <h2 className="text-sm font-semibold">{title}</h2>
      </div>
      {children}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="p-3 rounded-lg border border-border text-center">
      <div className="text-lg font-bold">{value}</div>
      <div className="text-[10px] text-muted-foreground">{label}</div>
    </div>
  );
}
