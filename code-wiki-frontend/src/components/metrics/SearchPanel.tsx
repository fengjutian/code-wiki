import { useEffect, useState } from "react";

export function SearchPanel() {
  const [patterns, setPatterns] = useState<Array<{name: string; label: string; description: string; languages: string[]}>>([]);
  const [results, setResults] = useState<Array<{file: string; line: number; match: string; language: string}>>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/search/pattern?list_patterns=true");
        if (res.ok) setPatterns((await res.json()).patterns || []);
      } catch { /* */ }
    })();
  }, []);

  const search = async (pattern: string) => {
    setSelected(pattern);
    setLoading(true);
    try {
      const res = await fetch(`/api/search/pattern?pattern=${pattern}`);
      if (res.ok) setResults((await res.json()).results || []);
    } catch { /* */ }
    setLoading(false);
  };

  return (
    <div className="h-full min-h-0 overflow-y-auto p-6">
      <h2 className="text-lg font-semibold mb-6">语义代码搜索</h2>

      <div className="flex flex-wrap gap-2 mb-4">
        {patterns.map(p => (
          <button key={p.name} onClick={() => search(p.name)}
            className={`px-3 py-1.5 text-xs rounded transition-colors ${
              selected === p.name ? "bg-primary text-primary-foreground" : "bg-secondary hover:bg-accent"
            }`}
            title={p.description}>
            {p.label}
            <span className="ml-1 text-[10px] opacity-60">({p.languages.join(",")})</span>
          </button>
        ))}
      </div>

      {loading && <p className="text-sm text-muted-foreground">搜索中...</p>}

      {results.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground mb-2">找到 {results.length} 条结果</p>
          {results.map((r, i) => (
            <div key={i} className="flex items-center gap-3 p-2 rounded bg-card border border-border text-xs hover:bg-accent transition-colors">
              <code className="font-mono shrink-0 text-muted-foreground w-48 truncate">{r.file}:{r.line}</code>
              <code className="truncate flex-1">{r.match}</code>
              <span className="text-[10px] text-muted-foreground shrink-0">{r.language}</span>
            </div>
          ))}
        </div>
      )}

      {!loading && results.length === 0 && (
        <div className="text-sm text-muted-foreground mt-12 text-center">
          <p>选择一个搜索模式开始搜索</p>
          <p className="text-xs mt-1">支持: 环境变量读取、SQL 查询、HTTP 请求、文件写入等</p>
        </div>
      )}
    </div>
  );
}
