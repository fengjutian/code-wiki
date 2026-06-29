// ---- 应用配置 (snake_case — matches backend JSON) ----
export interface LLMConfig {
  api_key: string;
  model: "deepseek-v4-flash" | "deepseek-v4-pro";
  base_url: string;
  temperature: number;
}

export interface AppConfig {
  repo_path: string;
  wiki_path: string;
  languages: string[];
  exclude_patterns: string[];
  llm: LLMConfig;
  theme: "light" | "dark" | "system";
}

// ---- 分析状态 (matches backend SSE progress events, converted from snake_case) ----
export interface AnalysisStatus {
  status: "idle" | "scanning" | "analyzing" | "generating" | "done" | "error" | "cancelling" | "cancelled";
  progress: number;
  currentStep: string;
  startedAt: string | null;
  finishedAt: string | null;
  totalModules: number;
  processedModules: number;
  totalWiki: number;
  processedWiki: number;
  errorMessage?: string;
}

// ---- 文件树 ----
export interface FileTreeNode {
  name: string;
  path: string;
  type: "file" | "directory";
  status: "pending" | "analyzed" | "error";
  excluded: boolean;
  children?: FileTreeNode[];
}

// ---- Wiki 树 ----
export interface WikiTreeNode {
  name: string;
  path: string;
  sourcePath?: string;
  type: "file" | "directory";
  children?: WikiTreeNode[];
}

// ---- 聊天消息 ----
export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

// ---- 默认值 ----
export const DEFAULT_EXCLUDE_PATTERNS = [
  "__pycache__/",
  ".git/",
  "node_modules/",
  ".venv/",
  "dist/",
  "build/",
  "*.pyc",
  ".code-wiki/",
];

export const DEFAULT_LANGUAGES = ["python", "typescript", "javascript"];

export const DEFAULT_LLM_CONFIG: LLMConfig = {
  api_key: "",
  model: "deepseek-v4-flash",
  base_url: "https://api.deepseek.com",
  temperature: 0.3,
};
