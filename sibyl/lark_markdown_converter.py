"""Markdown → Feishu Block deterministic converter.

Converts standard Markdown to Feishu document block format, replacing
LLM-based conversion with deterministic parsing.

Feishu Block Types:
- 2: text (paragraph)
- 3: heading1
- 4: heading2
- 5: heading3
- 12: bullet
- 13: ordered
- 14: code
- table: special handling via create_table API
"""

from __future__ import annotations

import re
from typing import Any


class MarkdownToFeishuConverter:
    """Convert Markdown text to a list of Feishu block dicts."""

    def convert(self, markdown: str) -> list[dict]:
        """Convert markdown string to Feishu block list.

        Returns list of block dicts. Tables are returned as special
        {"type": "table", "rows": int, "cols": int, "cells": [...]} markers
        for the caller to handle via create_table API.
        """
        lines = markdown.split("\n")
        blocks: list[dict] = []
        i = 0

        while i < len(lines):
            line = lines[i]

            # Empty line → skip
            if not line.strip():
                i += 1
                continue

            # Heading
            heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
            if heading_match:
                level = len(heading_match.group(1))
                text = heading_match.group(2).strip()
                blocks.append(self._heading_block(level, text))
                i += 1
                continue

            # Code fence
            if line.strip().startswith("```"):
                code_lines, end_i = self._parse_code_block(lines, i)
                lang = line.strip()[3:].strip()
                blocks.append(self._code_block("\n".join(code_lines), lang))
                i = end_i + 1
                continue

            # Table (pipe-delimited)
            if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|[\s\-:|]+\|\s*$", lines[i + 1]):
                table_block, end_i = self._parse_table(lines, i)
                if table_block:
                    blocks.append(table_block)
                i = end_i + 1
                continue

            # Bullet list
            bullet_match = re.match(r"^(\s*)[-*+]\s+(.+)$", line)
            if bullet_match:
                text = bullet_match.group(2)
                blocks.append(self._bullet_block(text))
                i += 1
                continue

            # Ordered list
            ordered_match = re.match(r"^(\s*)\d+[.)]\s+(.+)$", line)
            if ordered_match:
                text = ordered_match.group(2)
                blocks.append(self._ordered_block(text))
                i += 1
                continue

            # Default: paragraph text
            # Collect consecutive non-empty, non-special lines
            para_lines = []
            while i < len(lines) and lines[i].strip() and not self._is_special_line(lines[i]):
                para_lines.append(lines[i])
                i += 1
            if para_lines:
                blocks.append(self._text_block(" ".join(para_lines)))
                continue

            i += 1

        return blocks

    def _is_special_line(self, line: str) -> bool:
        """Check if a line starts a special block."""
        stripped = line.strip()
        if stripped.startswith("#"):
            return True
        if stripped.startswith("```"):
            return True
        if re.match(r"^[-*+]\s+", stripped):
            return True
        if re.match(r"^\d+[.)]\s+", stripped):
            return True
        return False

    def _heading_block(self, level: int, text: str) -> dict:
        block_type = {1: 3, 2: 4, 3: 5}.get(level, 5)
        return {
            "block_type": block_type,
            "heading": {
                "elements": self._parse_inline_styles(text),
            },
        }

    def _text_block(self, text: str) -> dict:
        return {
            "block_type": 2,
            "text": {
                "elements": self._parse_inline_styles(text),
            },
        }

    def _bullet_block(self, text: str) -> dict:
        return {
            "block_type": 12,
            "bullet": {
                "elements": self._parse_inline_styles(text),
            },
        }

    def _ordered_block(self, text: str) -> dict:
        return {
            "block_type": 13,
            "ordered": {
                "elements": self._parse_inline_styles(text),
            },
        }

    def _code_block(self, code: str, language: str = "") -> dict:
        return {
            "block_type": 14,
            "code": {
                "elements": [{"text_run": {"content": code}}],
                "language": _map_code_language(language),
            },
        }

    def _parse_code_block(self, lines: list[str], start: int) -> tuple[list[str], int]:
        """Parse a fenced code block, return (code_lines, end_index)."""
        code_lines: list[str] = []
        i = start + 1
        while i < len(lines):
            if lines[i].strip().startswith("```"):
                return code_lines, i
            code_lines.append(lines[i])
            i += 1
        return code_lines, i - 1

    def _parse_table(self, lines: list[str], start: int) -> tuple[dict | None, int]:
        """Parse a Markdown table. Returns (table_block, end_index)."""
        # Header row
        header = self._parse_table_row(lines[start])
        if not header:
            return None, start

        # Skip separator row
        i = start + 2

        # Data rows
        rows = [header]
        while i < len(lines) and "|" in lines[i]:
            row = self._parse_table_row(lines[i])
            if row:
                rows.append(row)
            i += 1

        cols = max(len(row) for row in rows) if rows else 0
        # Normalize all rows to same column count
        cells: list[list[str]] = []
        for row in rows:
            padded = row + [""] * (cols - len(row))
            cells.append(padded[:cols])

        return {
            "type": "table",
            "rows": len(cells),
            "cols": cols,
            "cells": cells,
        }, i - 1

    def _parse_table_row(self, line: str) -> list[str] | None:
        """Parse a single Markdown table row."""
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            # Try without leading/trailing pipes
            parts = [cell.strip() for cell in stripped.split("|")]
            parts = [p for p in parts if p]
            return parts if parts else None

        parts = stripped[1:-1].split("|")
        return [p.strip() for p in parts]

    def _parse_inline_styles(self, text: str) -> list[dict]:
        """Parse **bold**, *italic*, `code` inline styles.

        Returns a list of text_run elements with appropriate textStyles.
        """
        elements: list[dict] = []
        pos = 0

        # Pattern: **bold**, *italic*, `code`
        pattern = re.compile(
            r"\*\*(.+?)\*\*"   # bold
            r"|(?<!\*)\*([^*]+?)\*(?!\*)"  # italic (not bold)
            r"|`([^`]+?)`"     # inline code
        )

        for match in pattern.finditer(text):
            # Add plain text before this match
            if match.start() > pos:
                plain = text[pos:match.start()]
                if plain:
                    elements.append({"text_run": {"content": plain}})

            if match.group(1):  # bold
                elements.append({
                    "text_run": {
                        "content": match.group(1),
                        "text_element_style": {"bold": True},
                    }
                })
            elif match.group(2):  # italic
                elements.append({
                    "text_run": {
                        "content": match.group(2),
                        "text_element_style": {"italic": True},
                    }
                })
            elif match.group(3):  # code
                elements.append({
                    "text_run": {
                        "content": match.group(3),
                        "text_element_style": {"inline_code": True},
                    }
                })

            pos = match.end()

        # Remaining plain text
        if pos < len(text):
            remaining = text[pos:]
            if remaining:
                elements.append({"text_run": {"content": remaining}})

        # If no styles found, return plain text
        if not elements:
            elements.append({"text_run": {"content": text}})

        return elements


def _map_code_language(lang: str) -> int:
    """Map common language names to Feishu language enum values."""
    mapping = {
        "python": 49,
        "py": 49,
        "javascript": 26,
        "js": 26,
        "typescript": 62,
        "ts": 62,
        "bash": 7,
        "sh": 7,
        "shell": 7,
        "json": 28,
        "yaml": 68,
        "yml": 68,
        "latex": 33,
        "tex": 33,
        "sql": 56,
        "go": 19,
        "rust": 53,
        "java": 25,
        "c": 9,
        "cpp": 10,
        "c++": 10,
        "html": 21,
        "css": 12,
        "markdown": 38,
        "md": 38,
        "": 0,  # plaintext
    }
    return mapping.get(lang.lower().strip(), 0)
