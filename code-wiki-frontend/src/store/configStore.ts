import { create } from "zustand";
import type {
  FileTreeNode,
  WikiTreeNode,
  AnalysisStatus,
  ChatMessage,
  LLMConfig,
  AppConfig,
} from "@/lib/types";
import { DEFAULT_EXCLUDE_PATTERNS, DEFAULT_LLM_CONFIG, DEFAULT_LANGUAGES } from "@/lib/types";

/** Ensure every LLMConfig field has a defined value, merging with defaults. */
function sanitizeLLMConfig(raw: Partial<LLMConfig> | undefined | null): LLMConfig {
  return {
    api_key: raw?.api_key ?? DEFAULT_LLM_CONFIG.api_key,
    model: raw?.model ?? DEFAULT_LLM_CONFIG.model,
    base_url: raw?.base_url ?? DEFAULT_LLM_CONFIG.base_url,
    temperature: raw?.temperature ?? DEFAULT_LLM_CONFIG.temperature,
  };
}

// ---- Store Shape ----
interface ConfigState {
  // Tab
  activeTab: "code" | "wiki" | "analysis" | "settings" | "chat" | "test";
  setActiveTab: (tab: ConfigState["activeTab"]) => void;

  // Chat
  chatOpen: boolean;
  toggleChat: () => void;

  // Theme
  theme: "light" | "dark" | "system";
  setTheme: (t: ConfigState["theme"]) => void;

  // Config
  repoPath: string;
  wikiPath: string;
  languages: string[];
  excludePatterns: string[];
  llm: LLMConfig;

  // Analysis
  analysisStatus: AnalysisStatus;
  setAnalysisStatus: (s: Partial<AnalysisStatus>) => void;

  // Data
  fileTree: FileTreeNode[];
  wikiTree: WikiTreeNode[];
  wikiContent: string | null;

  // Code viewing
  viewingFilePath: string | null;
  codeContent: string | null;
  codeLoading: boolean;

  // Actions
  setRepoPath: (p: string) => void;
  setWikiPath: (p: string) => void;
  setLanguages: (langs: string[]) => void;
  setExcludePatterns: (patterns: string[]) => void;
  setLLM: (llm: LLMConfig) => void;
  saveApiKeyToLocal: () => void;
  fetchConfig: () => Promise<void>;
  saveConfig: () => Promise<void>;
  triggerScan: (mode: "full" | "partial", files?: string[]) => Promise<void>;
  cancelScan: () => Promise<void>;
  fetchFileTree: () => Promise<void>;
  fetchWikiTree: () => Promise<void>;
  fetchWikiContent: (path: string) => Promise<void>;
  // Code viewing
  setViewingFile: (path: string | null) => void;
  fetchCodeContent: (path: string) => Promise<void>;
}

// ---- Polling fallback for SSE ----
let _pollInterval: ReturnType<typeof setInterval> | null = null;

function startStatusPolling() {
  stopStatusPolling();
  _pollInterval = setInterval(async () => {
    try {
      const res = await fetch("/api/status");
      if (!res.ok) return;
      const raw = await res.json();
      // Convert snake_case to camelCase
      const data: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(raw)) {
        const camelKey = k.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
        data[camelKey] = v;
      }
      const store = useConfigStore.getState();
      store.setAnalysisStatus(data as Partial<AnalysisStatus>);
      // Stop polling when done or error
      if (data.status === "done" || data.status === "error") {
        stopStatusPolling();
        store.fetchWikiTree();
        store.fetchFileTree();
      }
    } catch { /* ignore */ }
  }, 2000);
}

function stopStatusPolling() {
  if (_pollInterval !== null) {
    clearInterval(_pollInterval);
    _pollInterval = null;
  }
}

export const useConfigStore = create<ConfigState>((set, get) => ({
  // ---- Initial State ----
  activeTab: "code",
  setActiveTab: (tab) => set({ activeTab: tab }),

  chatOpen: false,
  toggleChat: () => set((s) => ({ chatOpen: !s.chatOpen })),

  theme: "system",
  setTheme: (theme) => {
    set({ theme });
    localStorage.setItem("code-wiki-theme", theme);
  },

  // Load repoPath from localStorage for Tauri mode (no backend needed)
  repoPath: localStorage.getItem("code-wiki-repo-path") || "",
  wikiPath: localStorage.getItem("code-wiki-wiki-path") || "",
  languages: [...DEFAULT_LANGUAGES],
  excludePatterns: [...DEFAULT_EXCLUDE_PATTERNS],
  llm: {
    ...DEFAULT_LLM_CONFIG,
    api_key: localStorage.getItem("code-wiki-api-key") || "",
  },

  analysisStatus: {
    status: "idle",
    progress: 0,
    currentStep: "",
    startedAt: null,
    finishedAt: null,
    totalModules: 0,
    processedModules: 0,
    totalWiki: 0,
    processedWiki: 0,
  },
  setAnalysisStatus: (partial) =>
    set((s) => ({ analysisStatus: { ...s.analysisStatus, ...partial } })),

  fileTree: [],
  wikiTree: [],
  wikiContent: null,

  // Code viewing
  viewingFilePath: null,
  codeContent: null,
  codeLoading: false,

  // ---- Setters ----
  setRepoPath: (repoPath) => {
    set({ repoPath });
    localStorage.setItem("code-wiki-repo-path", repoPath);
    debouncedSave();
  },
  setWikiPath: (wikiPath) => {
    set({ wikiPath });
    localStorage.setItem("code-wiki-wiki-path", wikiPath);
    debouncedSave();
  },
  setLanguages: (languages) => {
    set({ languages });
    get().saveConfig();
  },
  setExcludePatterns: (patterns) => {
    set({ excludePatterns: patterns });
    get().saveConfig();
  },
  saveApiKeyToLocal: () => {
    const key = get().llm.api_key;
    if (key) {
      localStorage.setItem("code-wiki-api-key", key);
    } else {
      localStorage.removeItem("code-wiki-api-key");
    }
  },

  setLLM: (llm) => {
    set({ llm });
    get().saveConfig();
  },

  // ---- API Actions ----
  fetchConfig: async () => {
    try {
      const res = await fetch("/api/config");
      if (!res.ok) return;
      const data: AppConfig = await res.json();
      set({
        repoPath: data.repo_path,
        wikiPath: data.wiki_path || "",
        languages: data.languages || [...DEFAULT_LANGUAGES],
        excludePatterns: data.exclude_patterns,
        llm: {
          ...sanitizeLLMConfig(data.llm),
          api_key: data.llm?.api_key || localStorage.getItem("code-wiki-api-key") || "",
        },
        theme: data.theme,
      });
      // Sync localStorage with backend value
      if (data.repo_path) {
        localStorage.setItem("code-wiki-repo-path", data.repo_path);
      }
      // Auto-sync api_key to backend if we have one stored locally (e.g. after restart)
      // Only sync once per session to avoid repeated PUTs
      const storedKey = localStorage.getItem("code-wiki-api-key");
      if (storedKey && !sessionStorage.getItem("code-wiki-api-synced")) {
        sessionStorage.setItem("code-wiki-api-synced", "1");
        await get().saveConfig();
      }
    } catch {
      // Backend not available yet — use defaults (localStorage already loaded at init)
    }
  },

  saveConfig: async () => {
    const { repoPath, wikiPath, languages, excludePatterns, llm, theme } = get();
    try {
      await fetch("/api/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_path: repoPath, wiki_path: wikiPath, languages, exclude_patterns: excludePatterns, llm, theme }),
      });
    } catch {
      // Ignore if backend not available
    }
  },

  triggerScan: async (mode, files) => {
    const { llm } = get();
    if (!llm.api_key) {
      set({
        analysisStatus: {
          status: "error",
          progress: 0,
          currentStep: "",
          startedAt: null,
          finishedAt: null,
          totalModules: 0,
          processedModules: 0,
          totalWiki: 0,
          processedWiki: 0,
          errorMessage: "请先在「设置 → LLM 配置」中填写 API Key 后再开始分析",
        },
      });
      return;
    }
    set({
      analysisStatus: {
        status: "scanning",
        progress: 0,
        currentStep: "开始扫描...",
        startedAt: new Date().toISOString(),
        finishedAt: null,
        totalModules: 0,
        processedModules: 0,
      },
    });
    try {
      await fetch("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, files: files || [] }),
      });
      // Start polling fallback — SSE is the primary channel, but if it drops,
      // polling /api/status every 2s will keep the UI updated.
      startStatusPolling();
    } catch (e) {
      set({
        analysisStatus: {
          status: "error",
          progress: 0,
          currentStep: "",
          startedAt: null,
          finishedAt: null,
          totalModules: 0,
          processedModules: 0,
          errorMessage: String(e),
        },
      });
    }
  },

  cancelScan: async () => {
    try {
      await fetch("/api/scan/cancel", { method: "POST" });
    } catch { /* ignore */ }
  },

  fetchFileTree: async () => {
    try {
      const res = await fetch("/api/files");
      if (res.ok) {
        const tree: FileTreeNode[] = await res.json();
        set({ fileTree: tree });
      }
    } catch { /* backend not available */ }
  },

  fetchWikiTree: async () => {
    try {
      const res = await fetch("/api/wiki/tree");
      if (res.ok) {
        const tree: WikiTreeNode[] = await res.json();
        set({ wikiTree: tree });
      }
    } catch { /* backend not available */ }
  },

  fetchWikiContent: async (path) => {
    try {
      const res = await fetch(`/api/wiki/${path}`);
      if (res.ok) {
        const content = await res.text();
        set({ wikiContent: content });
      }
    } catch {
      set({ wikiContent: null });
    }
  },

  setViewingFile: (path) => {
    set({ viewingFilePath: path, codeContent: null });
  },

  fetchCodeContent: async (rawPath) => {
    // Normalize Windows backslashes to forward slashes
    const path = rawPath.replace(/\\/g, "/");
    set({ codeLoading: true, codeContent: null });
    const repoPath = get().repoPath;
    try {
      // Try Tauri invoke first (desktop mode)
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        if (repoPath) {
          const content = await invoke<string>("read_file_content", {
            repoPath,
            filePath: path,
          });
          set({ codeContent: content, codeLoading: false });
          return;
        }
      } catch {
        // Tauri not available or command not found — will try HTTP API
      }
      // Fallback: HTTP API (browser dev mode)
      if (!repoPath) {
        set({ codeContent: `// 请先在设置中配置仓库路径`, codeLoading: false });
        return;
      }
      const res = await fetch(`/api/files/content?path=${encodeURIComponent(path)}`);
      if (res.ok) {
        const data = await res.json();
        set({ codeContent: data.content, codeLoading: false });
      } else if (res.status === 404) {
        set({ codeContent: `// 文件不存在: ${path}\n// 可能已被移动或删除`, codeLoading: false });
        get().fetchFileTree();
      } else {
        set({ codeContent: `// 无法加载文件 (${res.status}): ${res.statusText}`, codeLoading: false });
      }
    } catch (e) {
      set({ codeContent: `// 加载失败: ${e}`, codeLoading: false });
    }
  },
}));

// ---- Debounced config save (prevents excessive PUT requests during typing) ----
let _saveTimer: ReturnType<typeof setTimeout> | null = null;
function debouncedSave() {
  if (_saveTimer) clearTimeout(_saveTimer);
  _saveTimer = setTimeout(() => {
    _saveTimer = null;
    useConfigStore.getState().saveConfig();
  }, 300);
}
