"""
Database Schema Extractor — parses SQL files and ORM models for table/column/FK info.

Endpoint:
  GET /api/schema  — all tables, columns, and foreign key relationships
"""

import json
import logging
import re
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter

from config import get_wiki_path, get_config
from repositories.analysis_repo import AnalysisRepository

logger = logging.getLogger("code-wiki.schema")

router = APIRouter()

# ---------------------------------------------------------------------------
# SQL parsing
# ---------------------------------------------------------------------------

_CREATE_TABLE_RE = re.compile(
    r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?'
    r'[\`"\[]?(\w+)[\`"\]]?\s*\((.*?)\)\s*;',
    re.IGNORECASE | re.DOTALL,
)

_COLUMN_RE = re.compile(
    r'^\s*[\`"\[]?(\w+)[\`"\]]?\s+(\w+(?:\([^)]*\))?)',
    re.IGNORECASE,
)

_FK_RE = re.compile(
    r'FOREIGN\s+KEY\s*\([\`"\[]?(\w+)[\`"\]]?\)\s*REFERENCES\s+[\`"\[]?(\w+)[\`"\]]?\s*\([\`"\[]?(\w+)[\`"\]]?\)',
    re.IGNORECASE,
)

_PRIMARY_KEY_RE = re.compile(r'PRIMARY\s+KEY\s*\(([^)]+)\)', re.IGNORECASE)


def _parse_sql_file(filepath: Path) -> list[dict]:
    """Extract tables, columns, and FKs from a .sql file."""
    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    tables = []
    for match in _CREATE_TABLE_RE.finditer(content):
        table_name = match.group(1)
        body = match.group(2)

        columns = []
        # Split body by commas (naive but works for most cases)
        for line in body.split(","):
            col_match = _COLUMN_RE.match(line.strip())
            if col_match:
                col_name = col_match.group(1)
                col_type = col_match.group(2)
                is_pk = bool(re.search(
                    r'\bPRIMARY\s+KEY\b', line, re.IGNORECASE
                )) or bool(re.search(
                    r'\bAUTO_INCREMENT\b', line, re.IGNORECASE
                ))
                is_nullable = "NOT NULL" not in line.upper()
                columns.append({
                    "name": col_name,
                    "type": col_type,
                    "primary_key": is_pk,
                    "nullable": is_nullable,
                })

        # Foreign keys
        foreign_keys = []
        for fk_match in _FK_RE.finditer(body):
            foreign_keys.append({
                "column": fk_match.group(1),
                "referenced_table": fk_match.group(2),
                "referenced_column": fk_match.group(3),
            })

        tables.append({
            "name": table_name,
            "source": str(filepath),
            "columns": columns,
            "foreign_keys": foreign_keys,
            "type": "sql",
        })

    return tables


# ---------------------------------------------------------------------------
# ORM model parsing — reads actual source files for Column/relationship definitions
# ---------------------------------------------------------------------------

# Stricter ORM base detection — only match declarative Base, not BaseHTTPMiddleware etc.
_ORM_BASE_PATTERNS = [
    # Exact SQLAlchemy matches
    "DeclarativeBase",
    "db.Model",
    "Model",
    # Must be standalone "Base" not "BaseHTTPMiddleware" etc.
    # We handle Base separately with word-boundary check
]

def _is_orm_class(bases: list[str]) -> bool:
    """Check if a class inherits from a known ORM base."""
    for base in bases:
        base_clean = base.strip()
        # Exact match for known ORM bases
        if base_clean in ("DeclarativeBase", "db.Model", "Model", "Base", "AsyncBaseModel"):
            return True
        # Mixins and common SQLAlchemy patterns
        if base_clean in ("TimestampMixin", "BaseModel", "BaseMixin"):
            return True
        # Matches "Base" as a standalone part (e.g. "AsyncBaseModel" but not "BaseHTTPMiddleware")
        if "Base" in base_clean and base_clean not in (
            "BaseHTTPMiddleware", "BaseMiddleware", "BaseSettings",
            "BaseException", "BaseError", "BaseClass",
        ):
            return True
    return False

# Regex for extracting ORM definitions from source
_COLUMN_DEF_RE = re.compile(
    r'^\s*(\w+)\s*=\s*Column\s*\(\s*(\w+(?:\([^)]*\))?)',
    re.MULTILINE,
)

_FK_RE_DEF = re.compile(
    r'^\s*(\w+)\s*=\s*Column\s*\(.*?ForeignKey\s*\(\s*["\']([^"\']+)["\']\s*\).*?\)',
    re.MULTILINE | re.DOTALL,
)

_RELATIONSHIP_RE = re.compile(
    r'^\s*(\w+)\s*=\s*relationship\s*\(["\']([^"\']+)["\']',
    re.MULTILINE,
)

_TABLENAME_RE = re.compile(
    r'__tablename__\s*=\s*["\']([^"\']+)["\']',
)

_BACKREF_RE = re.compile(
    r'back_populates\s*=\s*["\']([^"\']+)["\']',
)


def _extract_orm_tables(modules: dict, repo_path: str) -> list[dict]:
    """Extract table definitions from ORM model classes by reading source files."""
    tables = []
    repo = Path(repo_path)

    for rel_path, mod in modules.items():
        for cls in mod.get("classes", []):
            name = cls.get("name", "")
            bases = cls.get("bases", [])
            is_orm = _is_orm_class(bases)
            if not is_orm:
                continue

            # Try to read actual source for column definitions
            columns = []
            foreign_keys = []
            relationships = []
            table_name = name.lower()

            try:
                source_path = repo / rel_path
                if source_path.exists():
                    source = source_path.read_text(encoding="utf-8", errors="replace")
                    # Extract class body (naive: from "class Name" to next top-level class or EOF)
                    class_body = _extract_class_body(source, name)

                    # __tablename__
                    tn_match = _TABLENAME_RE.search(class_body)
                    if tn_match:
                        table_name = tn_match.group(1)

                    # Column definitions
                    for col_match in _COLUMN_DEF_RE.finditer(class_body):
                        col_name = col_match.group(1)
                        col_type = col_match.group(2)
                        if col_name.startswith("_"):
                            continue
                        # Check if already listed (avoid duplicates from FK regex)
                        columns.append({
                            "name": col_name,
                            "type": col_type,
                            "primary_key": False,
                            "nullable": True,
                        })

                    # ForeignKey columns
                    fk_seen = set()
                    for fk_match in _FK_RE_DEF.finditer(class_body):
                        col_name = fk_match.group(1)
                        fk_ref = fk_match.group(2)  # e.g. "users.id"
                        if col_name in fk_seen:
                            continue
                        fk_seen.add(col_name)
                        parts = fk_ref.split(".")
                        foreign_keys.append({
                            "column": col_name,
                            "referenced_table": parts[0],
                            "referenced_column": parts[1] if len(parts) > 1 else "id",
                        })
                        # Mark column as FK
                        for c in columns:
                            if c["name"] == col_name:
                                c["type"] = f"FK({fk_ref})"
                                break

                    # relationship() definitions
                    for rel_match in _RELATIONSHIP_RE.finditer(class_body):
                        rel_name = rel_match.group(1)
                        rel_target = rel_match.group(2)
                        backref = ""
                        br_match = _BACKREF_RE.search(source[rel_match.start():rel_match.start()+500])
                        if br_match:
                            backref = br_match.group(1)
                        relationships.append({
                            "name": rel_name,
                            "target": rel_target,
                            "back_populates": backref,
                        })

            except Exception as e:
                logger.debug("Failed to read source for %s/%s: %s", rel_path, name, e)

            # Mark primary keys (id column, or column named like table_id)
            for c in columns:
                if c["name"] == "id":
                    c["primary_key"] = True
                    c["nullable"] = False
                # Check NOT NULL via source heuristics

            # Deduplicate columns by name
            seen_cols = set()
            unique_cols = []
            for c in columns:
                if c["name"] not in seen_cols:
                    seen_cols.add(c["name"])
                    unique_cols.append(c)

            tables.append({
                "name": table_name,
                "source": rel_path,
                "class_name": name,
                "columns": unique_cols,
                "foreign_keys": foreign_keys,
                "relationships": relationships,
                "type": "orm",
                "bases": bases,
            })

    return tables


def _extract_class_body(source: str, class_name: str) -> str:
    """Extract the body of a class definition from source code."""
    # Find "class ClassName(...)"
    pattern = re.compile(
        rf'class\s+{re.escape(class_name)}\s*(?:\([^)]*\))?\s*:',
        re.MULTILINE,
    )
    match = pattern.search(source)
    if not match:
        return source

    start = match.end()
    # Find the end: next line that starts at same or less indentation (non-empty, non-comment)
    body_lines = []
    lines = source[start:].split("\n")
    for line in lines:
        stripped = line.strip()
        # Stop at next class/def at top level or empty class-like definition
        if stripped and not line[0].isspace() and not stripped.startswith("#"):
            break
        body_lines.append(line)
    return "\n".join(body_lines)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/schema")
async def get_schema():
    """Return all extracted database tables and their relationships."""
    config = get_config()
    repo_path = config.get("repo_path", "")
    all_tables: list[dict] = []

    # 1. Parse raw SQL files
    if repo_path:
        repo = Path(repo_path)
        sql_files = list(repo.rglob("*.sql"))
        # Also check migrations dirs
        for pattern in ["**/migrations/**/*.sql", "**/alembic/**/*.sql"]:
            sql_files.extend(repo.rglob(pattern))

        seen = set()
        for sf in sql_files:
            if sf in seen:
                continue
            seen.add(sf)
            try:
                rel = sf.relative_to(repo)
            except ValueError:
                rel = sf
            all_tables.extend(_parse_sql_file(sf))

    # 2. Parse ORM models from analysis.json
    try:
        wiki = get_wiki_path()
        path = wiki / "analysis.json"
        if not path.exists():
            path = wiki.parent / "analysis.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                analysis = json.load(f)
            modules = analysis.get("modules", {})
            all_tables.extend(_extract_orm_tables(modules, repo_path))
    except Exception as e:
        logger.warning("Failed to load analysis for schema: %s", e)

    # Deduplicate by table name
    seen_names = set()
    unique_tables = []
    for t in all_tables:
        if t["name"] not in seen_names:
            seen_names.add(t["name"])
            unique_tables.append(t)

    # Build relationship edges
    edges = []
    for t in unique_tables:
        for fk in t.get("foreign_keys", []):
            edges.append({
                "source": t["name"],
                "target": fk["referenced_table"],
                "source_column": fk["column"],
                "target_column": fk.get("referenced_column", "id"),
                "type": "foreign_key",
            })

    # Detect implicit relationships (table B has column referencing table A name)
    table_names = {t["name"].lower() for t in unique_tables}
    for t in unique_tables:
        for col in t.get("columns", []):
            col_name = col["name"].lower()
            # column_name_id → column_name table
            if col_name.endswith("_id"):
                ref_name = col_name[:-3]  # strip _id
                # Check variants (plural, camelCase)
                for candidate in (ref_name, ref_name + "s", ref_name.replace("_", "")):
                    if candidate in table_names and candidate != t["name"].lower():
                        edges.append({
                            "source": t["name"],
                            "target": candidate,
                            "source_column": col["name"],
                            "target_column": "id",
                            "type": "implicit_fk",
                        })
                        break

    result = {
        "status": "ok",
        "tables": unique_tables,
        "edges": edges,
        "total_tables": len(unique_tables),
        "total_relationships": len(edges),
    }

    # Cache to .code-wiki/schema.json for Tauri local loading
    try:
        wiki_path = get_wiki_path()
        if wiki_path and wiki_path.exists():
            repo = AnalysisRepository(wiki_path)
            repo.save_schema(result)
    except Exception:
        pass

    return result
