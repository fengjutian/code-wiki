import { useCallback } from "react";

interface SourceLinkProps {
  file: string;
  line: number;
  repoPath?: string;
}

/**
 * Renders a clickable source link [→] from [@src:path:line] anchors.
 *
 * Click behavior:
 * 1. Try Tauri's open_in_editor command (opens file in system editor at line)
 * 2. Fallback: open file:// URL (works in browser dev mode)
 */
/**
 * Join repoPath and a relative file path into an absolute path.
 * Normalizes backslashes to forward slashes (Tauri/VS Code handle both on all OS).
 */
function resolveAbsolutePath(repoPath: string | undefined, relativePath: string): string {
  if (!repoPath) return relativePath;
  // Strip trailing slashes from repoPath, normalize to forward slashes
  const base = repoPath.replace(/\\/g, "/").replace(/\/+$/, "");
  return `${base}/${relativePath}`;
}

export function SourceLink({ file, line, repoPath }: SourceLinkProps) {
  const handleClick = useCallback(
    async (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();

      // Resolve relative → absolute path using repoPath
      const absolutePath = resolveAbsolutePath(repoPath, file);

      // Try Tauri command first
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        await invoke("open_in_editor", { path: absolutePath, line });
        return;
      } catch {
        // Tauri not available — try file:// fallback
      }

      // Fallback: show file path (modern browsers block file:// from http origins)
      // The Tauri invoke path above handles the actual open-in-editor flow
      // In dev mode, path is visible in the button title for manual copy
    },
    [file, line, repoPath]
  );

  return (
    <button
      onClick={handleClick}
      className="inline-flex items-center gap-0.5 px-1 py-0 text-[11px] 
                 text-blue-600 dark:text-blue-400 hover:underline 
                 bg-blue-50 dark:bg-blue-900/30 rounded 
                 hover:bg-blue-100 dark:hover:bg-blue-900/50
                 transition-colors cursor-pointer font-mono"
      title={`打开 ${resolveAbsolutePath(repoPath, file)}:${line}`}
    >
      [→ {file}:{line}]
    </button>
  );
}

/**
 * Custom ReactMarkdown component that renders <source-link> elements
 * (produced by the rehypeSourceLinks plugin) as clickable SourceLink buttons.
 *
 * react-markdown v9 does not support overriding the `text` component,
 * so we use a rehype plugin to transform [@src:...] into <source-link>
 * elements at the hast tree level instead.
 */
export function sourceLinkRenderer(repoPath?: string) {
  return {
    "source-link"({ file, line }: { file: string; line: number }) {
      return <SourceLink file={file} line={line} repoPath={repoPath} />;
    },
  };
}
