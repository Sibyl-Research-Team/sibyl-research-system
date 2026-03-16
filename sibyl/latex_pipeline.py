"""Deterministic LaTeX compilation pipeline.

Replaces LLM-driven paper.md → main.tex → PDF conversion with a code-first
pipeline using pandoc + latexmk. Falls back to LLM agent on compilation errors.

Saves ~30K tokens per LaTeX compilation cycle.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from sibyl._paths import REPO_ROOT

TEMPLATES_DIR = REPO_ROOT / "sibyl" / "templates"


def compile_full_pipeline(workspace_path: Path) -> dict:
    """Run the complete LaTeX compilation pipeline.

    Steps:
    1. paper.md → main.tex via pandoc
    2. references.json → references.bib
    3. Copy template files (neurips_2024)
    4. Copy figure files
    5. latexmk -pdf main.tex
    6. Parse compilation log

    Returns:
        {"status": "ok", "pdf_path": str} on success
        {"status": "error", "errors": [...], "needs_agent": True} on failure
    """
    ws = Path(workspace_path)
    paper_md = _find_paper_md(ws)
    if paper_md is None:
        return {
            "status": "error",
            "errors": [{"type": "missing_source", "message": "paper.md not found"}],
            "needs_agent": True,
        }

    # Setup latex output directory
    latex_dir = ws / "latex"
    latex_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Markdown → LaTeX via pandoc
    main_tex = latex_dir / "main.tex"
    success = markdown_to_latex_pandoc(paper_md, main_tex, template="neurips_2024")
    if not success:
        return {
            "status": "error",
            "errors": [{"type": "pandoc_failed", "message": "pandoc conversion failed"}],
            "needs_agent": True,
        }

    # Step 2: References → BibTeX
    refs_json = ws / "writing" / "references.json"
    refs_bib = latex_dir / "references.bib"
    if refs_json.exists():
        ref_count = references_to_bibtex(refs_json, refs_bib)
    else:
        ref_count = 0

    # Step 3: Copy template files
    _copy_template_files(latex_dir, template="neurips_2024")

    # Step 3.5: Pre-process figures (execute scripts, render desc placeholders)
    fig_results = _preprocess_figures(ws)

    # Step 4: Copy figures
    _copy_figures(ws, latex_dir)

    # Step 4.5: Clean up script-path references in the generated .tex
    if main_tex.exists():
        _clean_script_refs_in_tex(main_tex)

    # Step 5: Compile
    ok, error_log = run_latexmk(latex_dir)
    if ok:
        pdf_path = latex_dir / "main.pdf"
        return {
            "status": "ok",
            "pdf_path": str(pdf_path),
            "references": ref_count,
            "figures": fig_results,
        }

    # Step 6: Parse errors
    log_path = latex_dir / "main.log"
    errors = extract_latex_errors(log_path) if log_path.exists() else []
    if not errors and error_log:
        errors = [{"type": "compile_error", "message": error_log[:500]}]

    return {
        "status": "error",
        "errors": errors,
        "needs_agent": True,
        "log_path": str(log_path) if log_path.exists() else None,
    }


def _find_paper_md(ws: Path) -> Path | None:
    """Find the paper markdown source in the workspace."""
    candidates = [
        ws / "writing" / "paper.md",
        ws / "writing" / "integrated_paper.md",
        ws / "paper.md",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def markdown_to_latex_pandoc(
    paper_md_path: Path,
    output_path: Path,
    template: str = "neurips_2024",
) -> bool:
    """Convert Markdown to LaTeX using pandoc.

    Returns True on success, False on failure.
    """
    # Check if pandoc is available
    if shutil.which("pandoc") is None:
        return False

    pandoc_template = TEMPLATES_DIR / template / "neurips_pandoc.tex"

    cmd = [
        "pandoc",
        str(paper_md_path),
        "-o", str(output_path),
        "--from=markdown+tex_math_dollars+raw_tex",
        "--to=latex",
        "--standalone",
        "--natbib",
    ]

    # Use custom pandoc template if available
    if pandoc_template.exists():
        cmd.extend(["--template", str(pandoc_template)])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(paper_md_path.parent),
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def references_to_bibtex(refs_json_path: Path, output_path: Path) -> int:
    """Convert references.json to BibTeX format.

    Expected JSON format:
    [
        {
            "key": "smith2023",
            "type": "article",
            "title": "...",
            "author": "...",
            "year": "2023",
            "journal": "...",
            ...
        }
    ]

    Returns: number of references converted.
    """
    try:
        data = json.loads(refs_json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0

    if not isinstance(data, list):
        data = data.get("references", []) if isinstance(data, dict) else []

    entries: list[str] = []
    for ref in data:
        if not isinstance(ref, dict):
            continue
        key = ref.get("key", ref.get("id", f"ref{len(entries)}"))
        entry_type = ref.get("type", "article")
        fields: list[str] = []
        for field_name in ("title", "author", "year", "journal", "booktitle",
                           "volume", "number", "pages", "doi", "url",
                           "publisher", "note", "arxivId"):
            value = ref.get(field_name)
            if value:
                # Escape special BibTeX characters
                value = str(value).replace("&", r"\&")
                fields.append(f"  {field_name} = {{{value}}}")
        if fields:
            entry = f"@{entry_type}{{{key},\n" + ",\n".join(fields) + "\n}"
            entries.append(entry)

    output_path.write_text("\n\n".join(entries), encoding="utf-8")
    return len(entries)


def run_latexmk(latex_dir: Path) -> tuple[bool, str]:
    """Run latexmk to compile LaTeX to PDF.

    Returns (success, error_message).
    """
    # Try latexmk first, then pdflatex
    for tool in ("latexmk", "pdflatex"):
        if shutil.which(tool) is None:
            continue

        if tool == "latexmk":
            cmd = ["latexmk", "-pdf", "-interaction=nonstopmode", "main.tex"]
        else:
            # Run pdflatex twice for references
            cmd = ["pdflatex", "-interaction=nonstopmode", "main.tex"]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(latex_dir),
            )

            if tool == "pdflatex" and result.returncode == 0:
                # Run bibtex + pdflatex again for references
                bib_path = latex_dir / "references.bib"
                if bib_path.exists():
                    subprocess.run(
                        ["bibtex", "main"],
                        capture_output=True, text=True,
                        timeout=30, cwd=str(latex_dir),
                    )
                    subprocess.run(
                        cmd,
                        capture_output=True, text=True,
                        timeout=120, cwd=str(latex_dir),
                    )

            pdf_path = latex_dir / "main.pdf"
            if pdf_path.exists():
                return True, ""

            return False, result.stderr[:500] if result.stderr else result.stdout[-500:]
        except subprocess.TimeoutExpired:
            return False, f"{tool} timed out after 120s"
        except (FileNotFoundError, OSError) as exc:
            continue

    return False, "Neither latexmk nor pdflatex found on PATH"


def extract_latex_errors(log_path: Path) -> list[dict]:
    """Extract structured errors from LaTeX log file."""
    errors: list[dict] = []
    try:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return errors

    # Match lines starting with ! (LaTeX errors)
    error_pattern = re.compile(r"^! (.+)$", re.MULTILINE)
    for match in error_pattern.finditer(log_text):
        msg = match.group(1).strip()
        # Try to find the line number
        line_match = re.search(r"l\.(\d+)", log_text[match.end():match.end() + 200])
        line_num = int(line_match.group(1)) if line_match else None
        errors.append({
            "type": "latex_error",
            "message": msg,
            "line": line_num,
        })

    # Also check for undefined references
    undef_pattern = re.compile(r"Warning: Reference `([^']+)' on page", re.IGNORECASE)
    for match in undef_pattern.finditer(log_text):
        errors.append({
            "type": "undefined_reference",
            "message": f"Undefined reference: {match.group(1)}",
        })

    return errors


def _copy_template_files(latex_dir: Path, template: str = "neurips_2024") -> None:
    """Copy template .sty and related files to the latex output directory."""
    template_dir = TEMPLATES_DIR / template
    if not template_dir.exists():
        return
    for src in template_dir.iterdir():
        if src.suffix in (".sty", ".bst", ".cls"):
            dst = latex_dir / src.name
            if not dst.exists():
                shutil.copy2(src, dst)


def _copy_figures(ws: Path, latex_dir: Path) -> None:
    """Copy figure files from workspace to latex directory."""
    figures_dir = ws / "writing" / "figures"
    if not figures_dir.exists():
        return
    latex_figures = latex_dir / "figures"
    latex_figures.mkdir(exist_ok=True)
    for fig in figures_dir.iterdir():
        if fig.suffix.lower() in (".pdf", ".png", ".svg", ".jpg", ".jpeg", ".eps"):
            dst = latex_figures / fig.name
            if not dst.exists() or fig.stat().st_mtime > dst.stat().st_mtime:
                shutil.copy2(fig, dst)


# ---------------------------------------------------------------------------
# Figure pre-processing: execute scripts, render desc placeholders, clean refs
# ---------------------------------------------------------------------------

def _preprocess_figures(ws: Path) -> list[dict]:
    """Execute gen_*.py scripts and render *_desc.md placeholders.

    Returns a list of per-figure result dicts for diagnostics.
    """
    figures_dir = ws / "writing" / "figures"
    if not figures_dir.exists():
        return []

    results: list[dict] = []
    results.extend(_execute_figure_scripts(figures_dir))
    results.extend(_render_desc_placeholders(figures_dir))
    return results


def _execute_figure_scripts(figures_dir: Path) -> list[dict]:
    """Run gen_*.py scripts whose output PDF/PNG does not yet exist."""
    results: list[dict] = []
    venv_python = REPO_ROOT / ".venv" / "bin" / "python3"
    python_cmd = str(venv_python) if venv_python.exists() else "python3"

    for script in sorted(figures_dir.glob("gen_*.py")):
        figure_id = script.stem.removeprefix("gen_")
        expected_pdf = figures_dir / f"{figure_id}.pdf"
        expected_png = figures_dir / f"{figure_id}.png"

        if expected_pdf.exists() or expected_png.exists():
            results.append({
                "script": script.name, "status": "skipped",
                "reason": "output already exists",
            })
            continue

        try:
            proc = subprocess.run(
                [python_cmd, str(script)],
                capture_output=True, text=True, timeout=120,
                cwd=str(figures_dir),
            )
            if expected_pdf.exists() or expected_png.exists():
                results.append({"script": script.name, "status": "ok"})
            else:
                msg = (proc.stderr or proc.stdout or "")[:300]
                results.append({
                    "script": script.name, "status": "error",
                    "message": f"Script exited {proc.returncode} but output not found. {msg}",
                })
        except subprocess.TimeoutExpired:
            results.append({
                "script": script.name, "status": "error",
                "message": "Timed out after 120s",
            })
        except (FileNotFoundError, OSError) as exc:
            results.append({
                "script": script.name, "status": "error",
                "message": str(exc)[:200],
            })

    return results


def _render_desc_placeholders(figures_dir: Path) -> list[dict]:
    """Generate placeholder PDFs for *_desc.md files lacking a rendered image."""
    results: list[dict] = []

    for desc_file in sorted(figures_dir.glob("*_desc.md")):
        figure_id = desc_file.stem.removesuffix("_desc")
        # Check if any rendered output already exists
        if any((figures_dir / f"{figure_id}{ext}").exists()
               for ext in (".pdf", ".png", ".jpg")):
            results.append({
                "desc": desc_file.name, "status": "skipped",
                "reason": "rendered output already exists",
            })
            continue

        # Read the description and extract a title from the first non-empty line
        try:
            text = desc_file.read_text(encoding="utf-8")
        except OSError:
            continue

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        title = (lines[0].lstrip("#").strip() if lines else figure_id)[:80]

        output_pdf = figures_dir / f"{figure_id}.pdf"
        ok = _create_placeholder_pdf(output_pdf, title, figure_id)
        results.append({
            "desc": desc_file.name,
            "status": "ok" if ok else "error",
            "output": str(output_pdf) if ok else None,
        })

    return results


def _create_placeholder_pdf(output_path: Path, title: str, figure_id: str) -> bool:
    """Create a simple placeholder PDF for a description-only figure.

    Uses matplotlib to draw a labeled box.  Returns True on success.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyBboxPatch
    except ImportError:
        return False

    fig, ax = plt.subplots(figsize=(6, 3))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()

    # Draw a rounded box
    box = FancyBboxPatch(
        (0.05, 0.15), 0.9, 0.7,
        boxstyle="round,pad=0.05",
        facecolor="#f0f0f0", edgecolor="#888888", linewidth=1.5,
    )
    ax.add_patch(box)

    # Title
    ax.text(0.5, 0.7, title, ha="center", va="center",
            fontsize=11, fontweight="bold", wrap=True,
            transform=ax.transAxes)
    # Subtitle
    ax.text(0.5, 0.4, f"[{figure_id}]",
            ha="center", va="center", fontsize=9, color="#666666",
            transform=ax.transAxes)
    ax.text(0.5, 0.25, "See paper text for detailed description",
            ha="center", va="center", fontsize=8, fontstyle="italic",
            color="#999999", transform=ax.transAxes)

    try:
        fig.savefig(str(output_path), bbox_inches="tight", dpi=150)
        plt.close(fig)
        return True
    except OSError:
        plt.close(fig)
        return False


# Patterns matching inline script-path references that pandoc passes through.
# Examples:
#   (Generated from gen_foo.py; rendered as foo.pdf)
#   *(Generated from gen_bar.py)*
#   `gen_baz.py`  (standalone backtick reference in a caption)
_SCRIPT_REF_PATTERNS = [
    # "(Generated from gen_foo.py; rendered as foo.pdf)"
    re.compile(
        r"\(?Generated\s+from\s+\\?(?:texttt\{)?gen_[A-Za-z0-9_]+\.py\}?"
        r"(?:;\s*rendered\s+as\s+[A-Za-z0-9_]+\.pdf)?\)?\s*",
        re.IGNORECASE,
    ),
    # Italic wrapper: \emph{(Generated from …)}
    re.compile(
        r"\\emph\{[^}]*gen_[A-Za-z0-9_]+\.py[^}]*\}\s*",
        re.IGNORECASE,
    ),
    # Standalone \texttt{gen_foo.py}
    re.compile(
        r"\\texttt\{gen_[A-Za-z0-9_]+\.py\}\s*",
        re.IGNORECASE,
    ),
    # Bare gen_foo.py with escaped underscores (common pandoc output)
    # Matches gen\_foo\_bar.py where underscores are LaTeX-escaped
    re.compile(
        r"gen(?:\\_[A-Za-z0-9]+)+\.py\s*",
    ),
]


def _clean_script_refs_in_tex(tex_path: Path) -> None:
    """Remove literal gen_*.py script-path references from the generated .tex."""
    try:
        text = tex_path.read_text(encoding="utf-8")
    except OSError:
        return

    original = text
    for pat in _SCRIPT_REF_PATTERNS:
        text = pat.sub("", text)

    if text != original:
        tex_path.write_text(text, encoding="utf-8")
