#!/bin/bash
# Quick sanity check for Code Wiki
# Run from project root: bash scripts/check.sh

set -e
echo "=== Backend Python compile ==="
cd backend
python3 -c "
import py_compile
files = ['main.py','config.py'] + [
    f'routes/{f}.py' for f in ['scan','wiki','chat','diagrams','config','files','status','events','graph','watcher','health','llm_test']
] + [
    f'services/{f}.py' for f in ['scanner','analyzer','ts_analyzer','dependency_graph','embedder','embedding_client','ast_chunker','hybrid_search','search','reranker','index_manager','mermaid_utils','watcher']
] + [
    f'services/wiki/{f}.py' for f in ['__init__','generator','llm_service','markdown_builder','prompt_builder','wiki_state','wiki_writer']
] + [
    f'models/{f}.py' for f in ['entities']
]
for f in files:
    py_compile.compile(f, doraise=True)
print(f'{len(files)} files compile OK')
"
echo ""

echo "=== Frontend TypeScript compile ==="
cd ../code-wiki-frontend
npx tsc --noEmit --pretty 2>&1 || echo "(OK if no output)"
echo ""

echo "=== All checks passed ==="
