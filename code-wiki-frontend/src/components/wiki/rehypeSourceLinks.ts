/**
 * Rehype plugin that transforms [@src:path:line] patterns in text nodes
 * into <source-link> custom elements, which can then be rendered by
 * a matching component in react-markdown's components map.
 *
 * react-markdown v9 does not support overriding the `text` component
 * (hast-util-to-jsx-runtime returns text nodes as plain strings).
 * This plugin works around that limitation at the hast tree level.
 */
import { visit } from "unist-util-visit";

// Inline hast types (avoid dependency on @types/hast)
interface HastText { type: "text"; value: string; }
interface HastElement { type: "element"; tagName: string; properties: Record<string, unknown>; children: (HastText | HastElement)[]; }

const SRC_PATTERN = /(\[@src:[^\]]+\])/g;
const SRC_MATCH = /^\[@src:(.+):(\d+)\]$/;

export default function rehypeSourceLinks() {
  return function (tree: HastElement | HastText) {
    visit(tree, "text", (node: unknown, idx: unknown, parent: unknown) => {
      const index = idx as number | null;
      const p = parent as HastElement;
      if (!p || index === null) return;

      const textNode = node as HastText;
      const value = textNode.value;

      // Quick check before doing the split
      if (!value.includes("[@src:")) return;

      const parts = value.split(SRC_PATTERN);
      const replacements: (HastText | HastElement)[] = [];

      for (const part of parts) {
        const match = part.match(SRC_MATCH);
        if (match) {
          replacements.push({
            type: "element",
            tagName: "source-link",
            properties: {
              file: match[1],
              line: parseInt(match[2], 10),
            },
            children: [],
          });
        } else if (part) {
          replacements.push({ type: "text", value: part });
        }
      }

      // Replace the original text node with the new sequence
      p.children.splice(index, 1, ...replacements);
      return index + replacements.length;
    });
  };
}
