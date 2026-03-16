"""Tests for sibyl.latex_pipeline module."""

import json
import sys
from pathlib import Path

import pytest

from sibyl.latex_pipeline import (
    compile_full_pipeline,
    extract_latex_errors,
    references_to_bibtex,
    _find_paper_md,
    _copy_template_files,
    _execute_figure_scripts,
    _render_desc_placeholders,
    _clean_script_refs_in_tex,
    _preprocess_figures,
)


class TestFindPaperMd:
    def test_finds_paper_in_writing_dir(self, tmp_path):
        (tmp_path / "writing").mkdir()
        (tmp_path / "writing" / "paper.md").write_text("# Title")
        assert _find_paper_md(tmp_path) == tmp_path / "writing" / "paper.md"

    def test_finds_integrated_paper(self, tmp_path):
        (tmp_path / "writing").mkdir()
        (tmp_path / "writing" / "integrated_paper.md").write_text("# Title")
        assert _find_paper_md(tmp_path) == tmp_path / "writing" / "integrated_paper.md"

    def test_finds_paper_in_root(self, tmp_path):
        (tmp_path / "paper.md").write_text("# Title")
        assert _find_paper_md(tmp_path) == tmp_path / "paper.md"

    def test_returns_none_when_missing(self, tmp_path):
        assert _find_paper_md(tmp_path) is None


class TestReferencesToBibtex:
    def test_converts_references(self, tmp_path):
        refs = [
            {
                "key": "smith2023",
                "type": "article",
                "title": "A Great Paper",
                "author": "Smith, John",
                "year": "2023",
                "journal": "Nature",
            },
            {
                "key": "doe2024",
                "type": "inproceedings",
                "title": "Another Paper",
                "author": "Doe, Jane",
                "year": "2024",
                "booktitle": "NeurIPS 2024",
            },
        ]
        refs_path = tmp_path / "refs.json"
        refs_path.write_text(json.dumps(refs))
        output_path = tmp_path / "refs.bib"

        count = references_to_bibtex(refs_path, output_path)
        assert count == 2

        bib_text = output_path.read_text()
        assert "@article{smith2023" in bib_text
        assert "@inproceedings{doe2024" in bib_text
        assert "A Great Paper" in bib_text

    def test_handles_empty_file(self, tmp_path):
        refs_path = tmp_path / "refs.json"
        refs_path.write_text("[]")
        output_path = tmp_path / "refs.bib"
        assert references_to_bibtex(refs_path, output_path) == 0

    def test_handles_dict_format(self, tmp_path):
        refs_path = tmp_path / "refs.json"
        refs_path.write_text(json.dumps({
            "references": [{"key": "a", "type": "article", "title": "T", "year": "2024"}],
        }))
        output_path = tmp_path / "refs.bib"
        assert references_to_bibtex(refs_path, output_path) == 1

    def test_handles_missing_file(self, tmp_path):
        assert references_to_bibtex(tmp_path / "nope.json", tmp_path / "out.bib") == 0

    def test_escapes_ampersand(self, tmp_path):
        refs_path = tmp_path / "refs.json"
        refs_path.write_text(json.dumps([{
            "key": "x", "type": "article",
            "title": "A & B", "year": "2024",
        }]))
        output_path = tmp_path / "refs.bib"
        references_to_bibtex(refs_path, output_path)
        assert r"A \& B" in output_path.read_text()


class TestExtractLatexErrors:
    def test_extracts_errors(self, tmp_path):
        log = tmp_path / "main.log"
        log.write_text(
            "This is some log output\n"
            "! Undefined control sequence.\n"
            "l.42 \\badcommand\n"
            "More log output\n"
            "! Missing $ inserted.\n"
            "l.55 some text\n"
        )
        errors = extract_latex_errors(log)
        assert len(errors) == 2
        assert errors[0]["message"] == "Undefined control sequence."
        assert errors[0]["line"] == 42
        assert errors[1]["message"] == "Missing $ inserted."
        assert errors[1]["line"] == 55

    def test_handles_missing_log(self, tmp_path):
        assert extract_latex_errors(tmp_path / "nonexistent.log") == []

    def test_detects_undefined_references(self, tmp_path):
        log = tmp_path / "main.log"
        log.write_text("Warning: Reference `fig:abc' on page 3 undefined")
        errors = extract_latex_errors(log)
        assert any(e["type"] == "undefined_reference" for e in errors)


class TestCompileFullPipeline:
    def test_missing_paper_returns_error(self, tmp_path):
        result = compile_full_pipeline(tmp_path)
        assert result["status"] == "error"
        assert result["needs_agent"] is True
        assert any(e["type"] == "missing_source" for e in result["errors"])


class TestCopyTemplateFiles:
    def test_copies_sty_files(self, tmp_path):
        latex_dir = tmp_path / "latex"
        latex_dir.mkdir()
        _copy_template_files(latex_dir, template="neurips_2024")
        # Should copy neurips_2024.sty if template dir exists
        from sibyl._paths import REPO_ROOT
        template_sty = REPO_ROOT / "sibyl" / "templates" / "neurips_2024" / "neurips_2024.sty"
        if template_sty.exists():
            assert (latex_dir / "neurips_2024.sty").exists()


# ---------------------------------------------------------------------------
# Figure pre-processing tests
# ---------------------------------------------------------------------------

class TestExecuteFigureScripts:
    def test_skips_when_output_exists(self, tmp_path):
        figs = tmp_path / "figures"
        figs.mkdir()
        (figs / "gen_foo.py").write_text("print('hi')")
        (figs / "foo.pdf").write_text("fake pdf")

        results = _execute_figure_scripts(figs)
        assert len(results) == 1
        assert results[0]["status"] == "skipped"

    def test_executes_script_and_reports_ok(self, tmp_path):
        figs = tmp_path / "figures"
        figs.mkdir()
        # Script that creates its own output PDF
        script = figs / "gen_bar.py"
        script.write_text(
            "from pathlib import Path\n"
            "Path(__file__).parent.joinpath('bar.pdf').write_text('fake')\n"
        )

        results = _execute_figure_scripts(figs)
        assert len(results) == 1
        assert results[0]["status"] == "ok"
        assert (figs / "bar.pdf").exists()

    def test_reports_error_when_output_missing(self, tmp_path):
        figs = tmp_path / "figures"
        figs.mkdir()
        # Script that does NOT create output
        (figs / "gen_nope.py").write_text("pass\n")

        results = _execute_figure_scripts(figs)
        assert len(results) == 1
        assert results[0]["status"] == "error"
        assert "output not found" in results[0]["message"]

    def test_handles_no_scripts(self, tmp_path):
        figs = tmp_path / "figures"
        figs.mkdir()
        assert _execute_figure_scripts(figs) == []


class TestRenderDescPlaceholders:
    def test_skips_when_pdf_exists(self, tmp_path):
        figs = tmp_path / "figures"
        figs.mkdir()
        (figs / "arch_desc.md").write_text("# Architecture\nBoxes and arrows")
        (figs / "arch.pdf").write_text("fake pdf")

        results = _render_desc_placeholders(figs)
        assert len(results) == 1
        assert results[0]["status"] == "skipped"

    def test_generates_placeholder(self, tmp_path):
        pytest.importorskip("matplotlib")
        figs = tmp_path / "figures"
        figs.mkdir()
        (figs / "method_arch_desc.md").write_text("# Method Architecture\nEncoder → Decoder")

        results = _render_desc_placeholders(figs)
        assert len(results) == 1
        assert results[0]["status"] == "ok"
        assert (figs / "method_arch.pdf").exists()

    def test_handles_no_desc_files(self, tmp_path):
        figs = tmp_path / "figures"
        figs.mkdir()
        assert _render_desc_placeholders(figs) == []


class TestCleanScriptRefsInTex:
    def test_removes_generated_from_pattern(self, tmp_path):
        tex = tmp_path / "main.tex"
        tex.write_text(
            r"\caption{Results. (Generated from gen\_entropy.py; rendered as entropy.pdf)}"
            "\n"
        )
        _clean_script_refs_in_tex(tex)
        text = tex.read_text()
        assert "gen" not in text
        assert "entropy.py" not in text
        assert "Results." in text

    def test_removes_emph_wrapped_refs(self, tmp_path):
        tex = tmp_path / "main.tex"
        tex.write_text(
            r"\emph{(Generated from gen\_ablation.py; rendered as ablation.pdf)}"
            "\n"
        )
        _clean_script_refs_in_tex(tex)
        assert "gen" not in tex.read_text()

    def test_removes_bare_escaped_underscores(self, tmp_path):
        tex = tmp_path / "main.tex"
        tex.write_text(
            r"See gen\_attention\_heatmap.py for details."
            "\n"
        )
        _clean_script_refs_in_tex(tex)
        assert "gen\\_attention" not in tex.read_text()

    def test_preserves_normal_tex(self, tmp_path):
        tex = tmp_path / "main.tex"
        original = r"\includegraphics[width=\linewidth]{figures/foo.pdf}" + "\n"
        tex.write_text(original)
        _clean_script_refs_in_tex(tex)
        assert tex.read_text() == original

    def test_noop_when_file_missing(self, tmp_path):
        _clean_script_refs_in_tex(tmp_path / "nonexistent.tex")  # should not raise


class TestPreprocessFigures:
    def test_runs_both_scripts_and_descs(self, tmp_path):
        figs = tmp_path / "writing" / "figures"
        figs.mkdir(parents=True)
        # A script with existing output (skip)
        (figs / "gen_a.py").write_text("pass")
        (figs / "a.pdf").write_text("fake")
        # A desc without rendered output
        (figs / "b_desc.md").write_text("# Diagram B\nSome diagram")
        (figs / "b.png").write_text("fake")  # already rendered

        results = _preprocess_figures(tmp_path)
        assert len(results) == 2  # one script + one desc
        assert all(r["status"] == "skipped" for r in results)

    def test_returns_empty_when_no_figures_dir(self, tmp_path):
        assert _preprocess_figures(tmp_path) == []
