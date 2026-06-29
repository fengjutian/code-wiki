import { useMemo } from "react";
import { useConfigStore } from "@/store/configStore";
import Editor, { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { sourceLinkRenderer } from "@/components/wiki/SourceLink";
import rehypeSourceLinks from "@/components/wiki/rehypeSourceLinks";
import { rehypePrettyCodePlugin } from "@/components/wiki/rehypePrettyCode";

// Import Monaco workers via Vite's ?worker syntax so they are bundled correctly
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import TsWorker from "monaco-editor/esm/vs/language/typescript/ts.worker?worker";
import JsonWorker from "monaco-editor/esm/vs/language/json/json.worker?worker";
import CssWorker from "monaco-editor/esm/vs/language/css/css.worker?worker";
import HtmlWorker from "monaco-editor/esm/vs/language/html/html.worker?worker";

// Tell Monaco how to create web workers using the bundled worker scripts
self.MonacoEnvironment = {
  getWorker(_workerId: string, label: string): Worker {
    switch (label) {
      case "json":
        return new JsonWorker();
      case "css":
      case "scss":
      case "less":
        return new CssWorker();
      case "html":
      case "handlebars":
      case "razor":
        return new HtmlWorker();
      case "typescript":
      case "javascript":
        return new TsWorker();
      default:
        return new EditorWorker();
    }
  },
};

// Use locally installed monaco-editor instead of CDN (required for offline/desktop use)
loader.config({ monaco });

function detectLanguage(filePath: string): string {
  const ext = filePath.split(".").pop()?.toLowerCase() || "";
  const map: Record<string, string> = {
    py: "python",
    js: "javascript",
    jsx: "javascript",
    ts: "typescript",
    tsx: "typescript",
    json: "json",
    yaml: "yaml",
    yml: "yaml",
    md: "markdown",
    mdx: "markdown",
    toml: "toml",
    rs: "rust",
    sh: "shell",
    bash: "shell",
    css: "css",
    html: "html",
    xml: "xml",
    sql: "sql",
    go: "go",
    java: "java",
    kt: "kotlin",
    swift: "swift",
    rb: "ruby",
    php: "php",
    c: "c",
    cpp: "cpp",
    h: "c",
    hpp: "cpp",
    vue: "html",
    svelte: "html",
  };
  return map[ext] || "plaintext";
}

export function CodeViewer() {
  const viewingFilePath = useConfigStore((s) => s.viewingFilePath);
  const codeContent = useConfigStore((s) => s.codeContent);
  const codeLoading = useConfigStore((s) => s.codeLoading);
  const repoPath = useConfigStore((s) => s.repoPath);

  const language = useMemo(
    () => (viewingFilePath ? detectLanguage(viewingFilePath) : "plaintext"),
    [viewingFilePath]
  );

  const isMarkdown = useMemo(() => {
    if (!viewingFilePath) return false;
    const ext = viewingFilePath.split(".").pop()?.toLowerCase() || "";
    return ext === "md" || ext === "mdx";
  }, [viewingFilePath]);

  const renderer = useMemo(() => sourceLinkRenderer(repoPath), [repoPath]);

  if (!viewingFilePath) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground">
        <div className="text-center">
          <p className="text-2xl mb-2">📝</p>
          <p className="text-sm">点击左侧文件查看代码</p>
        </div>
      </div>
    );
  }

  if (codeLoading) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground">
        <div className="text-center">
          <p className="text-2xl mb-2">⏳</p>
          <p className="text-sm">加载中...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* File path header */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border bg-muted/30 shrink-0 text-xs text-muted-foreground font-mono">
        <span className="text-primary font-medium">📄</span>
        <span>{viewingFilePath}</span>
      </div>
      {/* Markdown preview for .md / .mdx files */}
      {isMarkdown ? (
        <div className="flex-1 overflow-y-auto p-6">
          <article className="prose dark:prose-invert max-w-none text-sm">
            <ReactMarkdown components={renderer} rehypePlugins={[rehypePrettyCodePlugin, rehypeSourceLinks]} remarkPlugins={[remarkGfm]}>{codeContent || ""}</ReactMarkdown>
          </article>
        </div>
      ) : (
        /* Monaco Editor for all other files */
        <div className="flex-1">
          <Editor
            language={language}
            value={codeContent || ""}
            theme="vs-dark"
            options={{
              readOnly: true,
              minimap: { enabled: false },
              lineNumbers: "on",
              scrollBeyondLastLine: false,
              wordWrap: "on",
              fontSize: 13,
              lineHeight: 22,
              padding: { top: 8 },
              automaticLayout: true,
            }}
            loading={
              <div className="h-full flex items-center justify-center text-muted-foreground">
                <p className="text-sm">加载编辑器...</p>
              </div>
            }
          />
        </div>
      )}
    </div>
  );
}
