"""
Wiki generation package.

Re-exports WikiGenerator from generator.py for backward compatibility.
Import as: from services.wiki import WikiGenerator
"""

from .generator import WikiGenerator

__all__ = ["WikiGenerator"]
