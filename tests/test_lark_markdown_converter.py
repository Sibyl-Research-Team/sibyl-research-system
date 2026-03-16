"""Tests for sibyl.lark_markdown_converter module."""

import pytest

from sibyl.lark_markdown_converter import MarkdownToFeishuConverter, _map_code_language


@pytest.fixture
def converter():
    return MarkdownToFeishuConverter()


class TestHeadings:
    def test_h1(self, converter):
        blocks = converter.convert("# Title")
        assert len(blocks) == 1
        assert blocks[0]["block_type"] == 3

    def test_h2(self, converter):
        blocks = converter.convert("## Subtitle")
        assert len(blocks) == 1
        assert blocks[0]["block_type"] == 4

    def test_h3(self, converter):
        blocks = converter.convert("### Sub-subtitle")
        assert len(blocks) == 1
        assert blocks[0]["block_type"] == 5


class TestParagraphs:
    def test_simple_paragraph(self, converter):
        blocks = converter.convert("This is a paragraph.")
        assert len(blocks) == 1
        assert blocks[0]["block_type"] == 2

    def test_multiline_paragraph(self, converter):
        blocks = converter.convert("Line one\nLine two")
        assert len(blocks) == 1
        assert "Line one Line two" in blocks[0]["text"]["elements"][0]["text_run"]["content"]

    def test_empty_lines_separate_paragraphs(self, converter):
        blocks = converter.convert("Para one\n\nPara two")
        assert len(blocks) == 2


class TestLists:
    def test_bullet_list(self, converter):
        blocks = converter.convert("- Item 1\n- Item 2\n- Item 3")
        assert len(blocks) == 3
        assert all(b["block_type"] == 12 for b in blocks)

    def test_ordered_list(self, converter):
        blocks = converter.convert("1. First\n2. Second\n3. Third")
        assert len(blocks) == 3
        assert all(b["block_type"] == 13 for b in blocks)

    def test_bullet_with_star(self, converter):
        blocks = converter.convert("* Item A\n* Item B")
        assert len(blocks) == 2
        assert all(b["block_type"] == 12 for b in blocks)


class TestCodeBlocks:
    def test_fenced_code(self, converter):
        md = "```python\nprint('hello')\n```"
        blocks = converter.convert(md)
        assert len(blocks) == 1
        assert blocks[0]["block_type"] == 14
        assert "print('hello')" in blocks[0]["code"]["elements"][0]["text_run"]["content"]
        assert blocks[0]["code"]["language"] == 49  # python

    def test_code_without_language(self, converter):
        md = "```\nsome code\n```"
        blocks = converter.convert(md)
        assert blocks[0]["code"]["language"] == 0  # plaintext


class TestTables:
    def test_simple_table(self, converter):
        md = "| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"
        blocks = converter.convert(md)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "table"
        assert blocks[0]["rows"] == 3  # header + 2 data rows
        assert blocks[0]["cols"] == 2

    def test_table_cells_content(self, converter):
        md = "| Name | Value |\n| --- | --- |\n| foo | bar |"
        blocks = converter.convert(md)
        cells = blocks[0]["cells"]
        assert cells[0] == ["Name", "Value"]
        assert cells[1] == ["foo", "bar"]


class TestInlineStyles:
    def test_bold(self, converter):
        blocks = converter.convert("This is **bold** text")
        elements = blocks[0]["text"]["elements"]
        bold_elements = [e for e in elements if e["text_run"].get("text_element_style", {}).get("bold")]
        assert len(bold_elements) == 1
        assert bold_elements[0]["text_run"]["content"] == "bold"

    def test_italic(self, converter):
        blocks = converter.convert("This is *italic* text")
        elements = blocks[0]["text"]["elements"]
        italic_elements = [e for e in elements if e["text_run"].get("text_element_style", {}).get("italic")]
        assert len(italic_elements) == 1
        assert italic_elements[0]["text_run"]["content"] == "italic"

    def test_inline_code(self, converter):
        blocks = converter.convert("Use `pip install` command")
        elements = blocks[0]["text"]["elements"]
        code_elements = [e for e in elements if e["text_run"].get("text_element_style", {}).get("inline_code")]
        assert len(code_elements) == 1
        assert code_elements[0]["text_run"]["content"] == "pip install"

    def test_mixed_styles(self, converter):
        blocks = converter.convert("**bold** and *italic* and `code`")
        elements = blocks[0]["text"]["elements"]
        assert len(elements) >= 5  # bold + " and " + italic + " and " + code


class TestComplexDocument:
    def test_mixed_content(self, converter):
        md = """# Research Report

## Introduction

This is a paragraph with **bold** and *italic* text.

- Point 1
- Point 2

## Results

| Metric | Value |
| --- | --- |
| Accuracy | 0.95 |

```python
print("done")
```
"""
        blocks = converter.convert(md)
        types = [b.get("block_type", b.get("type")) for b in blocks]
        assert 3 in types  # h1
        assert 4 in types  # h2
        assert 2 in types  # paragraph
        assert 12 in types  # bullet
        assert "table" in types  # table
        assert 14 in types  # code


class TestMapCodeLanguage:
    def test_known_languages(self):
        assert _map_code_language("python") == 49
        assert _map_code_language("javascript") == 26
        assert _map_code_language("bash") == 7

    def test_unknown_language(self):
        assert _map_code_language("fortran") == 0

    def test_case_insensitive(self):
        assert _map_code_language("Python") == 49
        assert _map_code_language("BASH") == 7
