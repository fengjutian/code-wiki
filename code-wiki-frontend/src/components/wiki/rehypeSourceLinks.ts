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
import type { Nodes, Text } from "hast";

const SRC_PATTERN = /(\[@src:[^\]]+\])/g;
const SRC_MATCH = /^\[@src:(.+):(\d+)\]$/;

export default function rehypeSourceLinks() {
  return function (tree: Nodes) {
    visit(tree, "text", (node, index, parent) => {
      if (!parent || index === undefined) return;

      const textNode = node as Text;
      const value = textNode.value;

      // Quick check before doing the split
      if (!value.includes("[@src:")) return;

      const parts = value.split(SRC_PATTERN);
      const replacements: (Text | import("hast").Element)[] = [];

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
      parent.children.splice(index, 1, ...replacements);
      // Return the new index to continue after the inserted nodes
      return index + replacements.length;
    });
  };
}
