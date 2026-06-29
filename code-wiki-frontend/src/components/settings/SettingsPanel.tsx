import { useState } from "react";
import { useConfigStore } from "@/store/configStore";

export function SettingsPanel() {
  const llm = useConfigStore((s) => s.llm);
  const setLLM = useConfigStore((s) => s.setLLM);
  const saveConfig = useConfigStore((s) => s.saveConfig);
  const theme = useConfigStore((s) => s.theme);
  const setTheme = useConfigStore((s) => s.setTheme);
  const [showKey, setShowKey] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);

  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await fetch("/api/llm/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          api_key: llm.api_key,
          model: llm.model,
          base_url: llm.base_url,
          temperature: llm.temperature,
        }),
      });
      const data = await res.json();
      if (data.ok) {
        setTestResult({
          ok: true,
          message: `✅ 连接成功！模型: ${data.model_used}，响应: ${data.response_preview || "(空)"}`,
        });
      } else {
        setTestResult({
          ok: false,
          message: `❌ ${data.error}${data.detail ? " — " + JSON.stringify(data.detail) : ""}`,
        });
      }
    } catch (e) {
      setTestResult({ ok: false, message: `❌ 请求失败: ${e}` });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-2xl mx-auto p-6 space-y-8">
        <h2 className="text-lg font-semibold">设置</h2>

        {/* ---- LLM 配置 ---- */}
        <section className="space-y-3">
          <h3 className="text-sm font-medium">🤖 LLM 配置</h3>
          <div>
            <label className="text-xs text-muted-foreground">API Key</label>
            <div className="flex gap-2 mt-1">
              <div className="flex-1 relative">
                <input
                  type={showKey ? "text" : "password"}
                  value={llm.api_key ?? ""}
                  onChange={(e) => {
                    setLLM({ ...llm, api_key: e.target.value });
                    setSaved(false);
                  }}
                  placeholder="sk-..."
                  className="w-full px-3 py-2 pr-9 text-sm rounded-md border border-input bg-background"
                />
                <button
                  type="button"
                  onClick={() => setShowKey(!showKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted-foreground hover:text-foreground px-1"
                  title={showKey ? "隐藏" : "显示"}
                >
                  {showKey ? "🙈" : "👁️"}
                </button>
              </div>
              <button
                type="button"
                onClick={async () => {
                  await saveConfig();
                  setSaved(true);
                  setTimeout(() => setSaved(false), 2000);
                }}
                className="px-3 py-2 text-sm rounded-md border border-input bg-background hover:bg-accent whitespace-nowrap"
              >
                {saved ? "✓ 已同步" : "💾 同步到后端"}
              </button>
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">模型</label>
            <select
              value={llm.model ?? ""}
              onChange={(e) =>
                setLLM({ ...llm, model: e.target.value as typeof llm.model })
              }
              className="w-full mt-1 px-3 py-2 text-sm rounded-md border border-input bg-background"
            >
              <option value="deepseek-v4-flash">DeepSeek V4 Flash（快速 · 推荐）</option>
              <option value="deepseek-v4-pro">DeepSeek V4 Pro（高质量）</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">API Base URL</label>
            <input
              type="text"
              value={llm.base_url ?? ""}
              onChange={(e) => setLLM({ ...llm, base_url: e.target.value })}
              className="w-full mt-1 px-3 py-2 text-sm rounded-md border border-input bg-background"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">
              Temperature: {llm.temperature.toFixed(1)}
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              value={llm.temperature ?? 0.3}
              onChange={(e) => setLLM({ ...llm, temperature: parseFloat(e.target.value) })}
              className="w-full mt-1"
            />
          </div>
          <button
            type="button"
            onClick={handleTestConnection}
            disabled={testing}
            className="w-full px-4 py-2 text-sm rounded-md border border-input bg-background hover:bg-accent disabled:opacity-50 transition-colors"
          >
            {testing ? "⏳ 测试中..." : "🔍 测试 DeepSeek 连接"}
          </button>
          {testResult && (
            <div
              className={`text-xs p-2 rounded-md ${
                testResult.ok
                  ? "bg-green-50 dark:bg-green-950/20 text-green-700 dark:text-green-300"
                  : "bg-red-50 dark:bg-red-950/20 text-red-700 dark:text-red-300"
              }`}
            >
              {testResult.message}
            </div>
          )}
        </section>

        {/* ---- 主题 ---- */}
        <section className="space-y-3">
          <h3 className="text-sm font-medium">🎨 主题切换</h3>
          <div className="flex gap-4">
            {(["light", "dark", "system"] as const).map((t) => (
              <label key={t} className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="radio"
                  name="theme"
                  value={t}
                  checked={theme === t}
                  onChange={() => setTheme(t)}
                />
                {t === "light" ? "☀️ 亮色" : t === "dark" ? "🌙 暗色" : "💻 跟随系统"}
              </label>
            ))}
          </div>
        </section>

        {/* ---- 关于 ---- */}
        <section className="space-y-1 pb-8">
          <h3 className="text-sm font-medium">ℹ️ 关于</h3>
          <p className="text-xs text-muted-foreground">Code Wiki v0.1.0</p>
        </section>
      </div>
    </div>
  );
}
