import { useState, useEffect } from "react";
import { DatabaseIcon, Table2Icon, Link2Icon, KeyIcon, SearchIcon, UsersIcon } from "lucide-react";

interface Column {
  name: string;
  type: string;
  primary_key: boolean;
  nullable: boolean;
}

interface Relation {
  name: string;
  target: string;
  back_populates: string;
}

interface TableDef {
  name: string;
  source: string;
  class_name?: string;
  columns: Column[];
  foreign_keys: { column: string; referenced_table: string; referenced_column: string }[];
  relationships?: Relation[];
  type: "sql" | "orm";
  bases?: string[];
}

interface SchemaEdge {
  source: string;
  target: string;
  source_column: string;
  target_column: string;
  type: "foreign_key" | "implicit_fk";
}

interface SchemaData {
  status: string;
  tables: TableDef[];
  edges: SchemaEdge[];
  total_tables: number;
  total_relationships: number;
}

export function SchemaPanel() {
  const [data, setData] = useState<SchemaData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showOrmOnly, setShowOrmOnly] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/schema");
        if (!res.ok) throw new Error(`${res.status}`);
        setData(await res.json());
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
        正在分析数据库结构...
      </div>
    );
  }

  if (error || !data || data.status !== "ok") {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground">
        <div className="text-center">
          <p className="text-3xl mb-3">🗄️</p>
          <p className="text-sm">{error || "暂无数据"}</p>
        </div>
      </div>
    );
  }

  // Build adjacency maps
  const forwardEdges = new Map<string, SchemaEdge[]>();
  const reverseEdges = new Map<string, SchemaEdge[]>();
  for (const edge of data.edges) {
    if (!forwardEdges.has(edge.source)) forwardEdges.set(edge.source, []);
    forwardEdges.get(edge.source)!.push(edge);
    if (!reverseEdges.has(edge.target)) reverseEdges.set(edge.target, []);
    reverseEdges.get(edge.target)!.push(edge);
  }

  // Filter: search + ORM toggle + selected table
  const q = search.toLowerCase();
  let shownTables = data.tables.filter((t) => {
    if (showOrmOnly && t.type !== "orm") return false;
    if (q) {
      return (
        t.name.toLowerCase().includes(q) ||
        (t.class_name && t.class_name.toLowerCase().includes(q)) ||
        t.columns.some((c) => c.name.toLowerCase().includes(q)) ||
        t.foreign_keys.some(
          (fk) => fk.referenced_table.toLowerCase().includes(q)
        )
      );
    }
    return true;
  });

  if (selectedTable) {
    const selName = selectedTable;
    shownTables = shownTables.filter((t) => {
      if (t.name === selName) return true;
      return (
        (forwardEdges.get(selName) || []).some((e) => e.target === t.name) ||
        (reverseEdges.get(selName) || []).some((e) => e.source === t.name)
      );
    });
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-3 p-3 border-b border-border shrink-0 flex-wrap">
        <DatabaseIcon size={18} className="text-primary" />
        <h1 className="text-sm font-semibold">数据库结构</h1>
        <span className="text-xs text-muted-foreground">
          {data.total_tables} 表 · {data.total_relationships} 关系
        </span>

        <div className="flex-1" />

        {/* Search */}
        <div className="relative">
          <SearchIcon size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索表名/列名/类名..."
            className="w-48 pl-6 pr-2 py-1 text-[11px] rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>

        {/* ORM filter */}
        <label className="flex items-center gap-1 text-[11px] text-muted-foreground cursor-pointer">
          <input
            type="checkbox"
            checked={showOrmOnly}
            onChange={(e) => setShowOrmOnly(e.target.checked)}
            className="rounded"
          />
          仅 ORM
        </label>

        {selectedTable && (
          <button
            onClick={() => setSelectedTable(null)}
            className="text-[11px] px-2 py-1 rounded bg-secondary hover:bg-accent transition-colors"
          >
            清除选择
          </button>
        )}
      </div>

      {/* Table Grid */}
      <div className="flex-1 overflow-auto p-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {shownTables.map((table) => {
            const relatedOut = forwardEdges.get(table.name) || [];
            const relatedIn = reverseEdges.get(table.name) || [];
            const isSelected = table.name === selectedTable;

            return (
              <div
                key={table.name}
                onClick={() => setSelectedTable(isSelected ? null : table.name)}
                className={`p-3 rounded-xl border cursor-pointer transition-all ${
                  isSelected
                    ? "border-primary bg-primary/5 ring-1 ring-primary"
                    : "border-border bg-card hover:bg-accent/30"
                }`}
              >
                {/* Header */}
                <div className="flex items-center gap-1.5 mb-2">
                  <Table2Icon size={13} className={isSelected ? "text-primary" : "text-muted-foreground"} />
                  <span className="font-mono text-xs font-medium truncate flex-1">{table.name}</span>
                  <span
                    className={`shrink-0 px-1 py-0.5 rounded text-[8px] ${
                      table.type === "sql" ? "bg-blue-500/10 text-blue-600" : "bg-purple-500/10 text-purple-600"
                    }`}
                  >
                    {table.type === "sql" ? "SQL" : "ORM"}
                  </span>
                </div>

                {table.class_name && (
                  <div className="text-[9px] text-muted-foreground mb-1 font-mono">
                    class {table.class_name}
                  </div>
                )}

                {/* Columns */}
                <div className="space-y-0.5 mb-2">
                  {table.columns.slice(0, 8).map((col) => (
                    <div key={col.name} className="flex items-center gap-1 text-[10px]">
                      {col.primary_key && <KeyIcon size={9} className="text-amber-500 shrink-0" />}
                      <span className="font-mono truncate">{col.name}</span>
                      <span className="text-muted-foreground shrink-0">{col.type}</span>
                    </div>
                  ))}
                  {table.columns.length > 8 && (
                    <div className="text-[9px] text-muted-foreground pl-4">+{table.columns.length - 8} 列</div>
                  )}
                  {table.columns.length === 0 && (
                    <div className="text-[9px] text-muted-foreground">暂无列信息</div>
                  )}
                </div>

                {/* Foreign Keys */}
                {table.foreign_keys.length > 0 && (
                  <div className="border-t border-border pt-1.5 space-y-0.5">
                    {table.foreign_keys.map((fk, i) => (
                      <div key={i} className="flex items-center gap-1 text-[9px]">
                        <Link2Icon size={8} className="text-primary shrink-0" />
                        <span className="font-mono">{fk.column}</span>
                        <span className="text-muted-foreground">→</span>
                        <span className="font-mono text-primary">{fk.referenced_table}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Relationships (ORM) */}
                {table.relationships && table.relationships.length > 0 && (
                  <div className="border-t border-border pt-1.5 space-y-0.5">
                    {table.relationships.map((rel, i) => (
                      <div key={i} className="flex items-center gap-1 text-[9px]">
                        <UsersIcon size={8} className="text-green-500 shrink-0" />
                        <span className="font-mono">{rel.name}</span>
                        <span className="text-muted-foreground">→</span>
                        <span className="font-mono text-green-600">{rel.target}</span>
                        {rel.back_populates && (
                          <span className="text-muted-foreground">({rel.back_populates})</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {/* Stats footer */}
                <div className="flex items-center gap-2 mt-2 text-[8px] text-muted-foreground/50">
                  <span>{table.columns.length} 列</span>
                  {table.foreign_keys.length > 0 && <span>· {table.foreign_keys.length} FK</span>}
                  {table.relationships && table.relationships.length > 0 && (
                    <span>· {table.relationships.length} 关联</span>
                  )}
                  <span className="truncate ml-auto">{table.source.split("/").pop()}</span>
                </div>
              </div>
            );
          })}
        </div>

        {shownTables.length === 0 && (
          <div className="text-center text-muted-foreground text-sm py-12">
            {search ? `未找到匹配 "${search}" 的表` : "暂无匹配的表"}
          </div>
        )}
      </div>
    </div>
  );
}
