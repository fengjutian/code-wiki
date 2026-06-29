import {unified} from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkRehype from 'remark-rehype';
import {visit} from 'unist-util-visit';

const SRC_PATTERN = /(\[@src:[^\]]+\])/g;
const SRC_MATCH = /^\[@src:(.+):(\d+)\]$/;

function rehypeSourceLinks() {
  return function(tree) {
    visit(tree, 'text', (node, index, parent) => {
      if (!parent || index === undefined) return;
      if (!node.value.includes('[@src:')) return;
      const parts = node.value.split(SRC_PATTERN);
      const replacements = [];
      for (const part of parts) {
        const match = part.match(SRC_MATCH);
        if (match) {
          replacements.push({
            type: 'element',
            tagName: 'source-link',
            properties: { file: match[1], line: parseInt(match[2], 10) },
            children: []
          });
        } else if (part) {
          replacements.push({ type: 'text', value: part });
        }
      }
      parent.children.splice(index, 1, ...replacements);
      return index + replacements.length;
    });
  };
}

const md = ;

try {
  const parser = unified().use(remarkParse).use(remarkGfm);
  const runner = unified().use(remarkRehype, {allowDangerousHtml: true}).use(rehypeSourceLinks);
  
  const mdast = parser.parse(md);
  console.log('Step 1: mdast parsed OK');
  
  const hast = await runner.run(mdast);
  console.log('Step 2: hast transformed OK');
  
  let count = 0;
  visit(hast, 'element', (node) => {
    if (node.tagName === 'source-link') {
      count++;
      console.log('  source-link:', node.properties.file + ':' + node.properties.line);
    }
    if (node.tagName === 'table') {
      console.log('  table found');
    }
  });
  console.log('Total source-links:', count);
  
} catch(e) {
  console.error('FAILED:', e.message);
  console.error(e.stack);
}
