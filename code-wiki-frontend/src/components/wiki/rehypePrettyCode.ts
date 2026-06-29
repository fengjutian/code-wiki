import rehypePrettyCode from "rehype-pretty-code";
import type { Options } from "rehype-pretty-code";

/**
 * Shared rehype-pretty-code configuration for the wiki/code/chat markdown renderers.
 *
 * Uses Shiki (VS Code engine) for token-level syntax highlighting.
 * Theme: github-dark-default — a modern dark theme matching the app's dark aesthetic.
 */
export const prettyCodeOptions: Options = {
  theme: "github-dark-default",
  keepBackground: true,
  defaultLang: "plaintext",
};

/** Pre-configured rehypePrettyCode plugin instance. */
export const rehypePrettyCodePlugin = [rehypePrettyCode, prettyCodeOptions] as const;
