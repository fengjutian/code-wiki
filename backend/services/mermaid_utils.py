"""
Shared Mermaid diagram utilities — sanitization helpers for labels and identifiers.

Used by:
- services/dependency_graph.py (dependency graph → Mermaid export)
- routes/diagrams.py (architecture / class / sequence diagram endpoints)
"""

import re


def sanitize_label(text: str) -> str:
    """Escape special chars for Mermaid labels inside quotes.
    Preserves <br/> tags (Mermaid line breaks) during sanitization.
    """
    # Protect Mermaid line break markers
    text = text.replace("<br/>", "\x00BR\x00")
    result = (
        text.replace('"', "'")
        .replace("[", "(")
        .replace("]", ")")
        .replace("{", "(")
        .replace("}", ")")
        .replace("<", "⟨")
        .replace(">", "⟩")
        .replace("&", "＆")
        .replace("#", "＃")
        .replace("\n", " ")
    )
    return result.replace("\x00BR\x00", "<br/>")


def sanitize_identifier(text: str) -> str:
    """Make a string safe for use as a Mermaid bare identifier (no quotes).
    Strips generic parameters and special chars."""
    # Strip generic type params: Generic[T] → Generic, List[int] → List
    # Also handle Foo<T>, Foo(T), Foo(int)
    text = re.sub(r'[\[\(<].*[\]\)>]$', '', text.strip())
    # Replace remaining dangerous chars with underscores
    return re.sub(r'[^a-zA-Z0-9_À-ÿ]', '_', text)
