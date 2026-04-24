"""Convert all docs/*.md to PDFs using a headless browser.

Strategy:
    1. Render Markdown to HTML with a professional print stylesheet.
    2. Invoke a headless Chromium/Chrome/Edge to print each HTML to PDF.
    3. Drop the PDFs in docs/pdf/.

Cross-platform: searches typical install locations on Windows, macOS and Linux.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
PDF_DIR = DOCS / "pdf"
HTML_DIR = DOCS / "_html_tmp"


def find_browser() -> Path:
    """Locate a Chromium-based browser suitable for headless --print-to-pdf.

    Honors the LDP_BROWSER environment variable if set; otherwise searches
    the standard install paths per platform.
    """
    override = os.environ.get("LDP_BROWSER")
    if override:
        p = Path(override)
        if p.exists():
            return p
        raise FileNotFoundError(f"LDP_BROWSER points to missing file: {p}")

    system = platform.system()
    candidates: list[Path] = []

    if system == "Windows":
        pf_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            Path(pf_x86) / "Google/Chrome/Application/chrome.exe",
            Path(pf) / "Google/Chrome/Application/chrome.exe",
            Path(local) / "Google/Chrome/Application/chrome.exe",
            Path(pf_x86) / "Microsoft/Edge/Application/msedge.exe",
            Path(pf) / "Microsoft/Edge/Application/msedge.exe",
        ]
    elif system == "Darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        ]
    else:  # Linux / other
        for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))

    for c in candidates:
        if c.exists():
            return c

    raise FileNotFoundError(
        "No Chromium-based browser found. Install Chrome/Edge/Chromium, or set "
        "the LDP_BROWSER environment variable to the path of the binary."
    )


CHROME = find_browser()

CSS = """
@page {
    size: A4;
    margin: 18mm 16mm 20mm 16mm;
    @bottom-right {
        content: counter(page) " / " counter(pages);
        font-size: 9pt;
        color: #666;
    }
}

* { box-sizing: border-box; }

body {
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 10.5pt;
    line-height: 1.55;
    color: #1f2328;
    max-width: 100%;
    margin: 0;
    padding: 0;
}

h1, h2, h3, h4 {
    font-weight: 600;
    line-height: 1.25;
    margin-top: 1.4em;
    margin-bottom: 0.5em;
    color: #0b1f33;
}

h1 {
    font-size: 22pt;
    border-bottom: 2px solid #0b3c6e;
    padding-bottom: 6pt;
    page-break-before: auto;
    color: #0b3c6e;
}

h2 {
    font-size: 16pt;
    border-bottom: 1px solid #d0d7de;
    padding-bottom: 4pt;
    margin-top: 1.8em;
    page-break-after: avoid;
}

h3 {
    font-size: 13pt;
    color: #24292f;
    page-break-after: avoid;
}

h4 {
    font-size: 11.5pt;
    color: #57606a;
    page-break-after: avoid;
}

p { margin: 0.6em 0; }

a { color: #0969da; text-decoration: none; }
a:hover { text-decoration: underline; }

code {
    font-family: "Cascadia Code", Consolas, "Courier New", monospace;
    font-size: 9pt;
    background: #f3f4f6;
    padding: 1px 5px;
    border-radius: 3px;
    color: #d1242f;
}

pre {
    background: #f6f8fa;
    border: 1px solid #d0d7de;
    border-radius: 4px;
    padding: 10pt 12pt;
    overflow-x: auto;
    font-size: 8.5pt;
    line-height: 1.45;
    page-break-inside: avoid;
}

pre code {
    background: transparent;
    color: #1f2328;
    padding: 0;
    font-size: 8.5pt;
    white-space: pre-wrap;
    word-wrap: break-word;
}

table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
    font-size: 9.5pt;
    page-break-inside: avoid;
}

th, td {
    border: 1px solid #d0d7de;
    padding: 5pt 8pt;
    text-align: left;
    vertical-align: top;
}

th {
    background: #f6f8fa;
    font-weight: 600;
    color: #24292f;
}

tr:nth-child(even) td { background: #fafbfc; }

blockquote {
    border-left: 3px solid #d0d7de;
    color: #57606a;
    padding: 4pt 12pt;
    margin: 1em 0;
    background: #f6f8fa;
}

ul, ol { padding-left: 22pt; margin: 0.6em 0; }
li { margin: 0.2em 0; }

hr {
    border: 0;
    border-top: 1px solid #d0d7de;
    margin: 1.5em 0;
}

img { max-width: 100%; }

.cover {
    page-break-after: always;
    padding: 60mm 0 0 0;
    text-align: center;
}
.cover h1 {
    font-size: 34pt;
    border: 0;
    color: #0b3c6e;
    margin-bottom: 10pt;
}
.cover .subtitle {
    font-size: 14pt;
    color: #57606a;
    margin-bottom: 40pt;
}
.cover .meta {
    font-size: 11pt;
    color: #57606a;
    margin-top: 80pt;
}
"""

HTML_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div class="cover">
    <h1>{title}</h1>
    <div class="subtitle">LegalDataPlatform</div>
    <div class="meta">
        Humberto Henriquez — Senior Data Engineer / Solutions Architect<br>
        Generado 2026-04-24
    </div>
</div>
{body}
</body>
</html>
"""


DOC_TITLES = {
    "WALKTHROUGH":            "Walkthrough completo — paso a paso",
    "INTERVIEW_SUMMARY":      "Resumen ejecutivo para entrevista",
    "ARCHITECTURE":           "Arquitectura",
    "PIPELINES":              "Pipelines ETL/ELT",
    "POSTGRESQL_OPTIMIZATION": "Optimización de PostgreSQL",
    "DATA_QUALITY":           "Calidad de datos — Fuente de verdad",
    "AWS_DEPLOYMENT":         "Despliegue en AWS",
}


def render_html(md_file: Path, html_file: Path) -> None:
    """Convert a Markdown file to a styled HTML file."""
    md_text = md_file.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        md_text,
        extensions=[
            "extra",          # tables, fenced code, attr_list, etc.
            "toc",
            "sane_lists",
            "codehilite",
            "nl2br",
        ],
        extension_configs={
            "codehilite": {"noclasses": True, "pygments_style": "default"},
        },
    )
    title = DOC_TITLES.get(md_file.stem, md_file.stem.replace("_", " ").title())
    html = HTML_TEMPLATE.format(title=title, css=CSS, body=html_body)
    html_file.write_text(html, encoding="utf-8")


def html_to_pdf(html_file: Path, pdf_file: Path) -> None:
    """Invoke the browser headless to print the HTML to PDF."""
    if not CHROME.exists():
        raise FileNotFoundError(f"Browser not found at {CHROME}")

    # Chrome expects file:// URIs with forward slashes
    file_url = html_file.resolve().as_uri()

    cmd = [
        str(CHROME),
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=10000",
        f"--print-to-pdf={pdf_file}",
        file_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if not pdf_file.exists() or pdf_file.stat().st_size < 1000:
        print(f"STDOUT: {result.stdout}", file=sys.stderr)
        print(f"STDERR: {result.stderr}", file=sys.stderr)
        raise RuntimeError(f"Chrome failed to produce {pdf_file}")


def main() -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    HTML_DIR.mkdir(parents=True, exist_ok=True)

    md_files = sorted([p for p in DOCS.glob("*.md") if p.is_file()])
    if not md_files:
        print("No markdown files found in docs/", file=sys.stderr)
        sys.exit(1)

    for md in md_files:
        html_path = HTML_DIR / f"{md.stem}.html"
        pdf_path = PDF_DIR / f"{md.stem}.pdf"
        print(f"  {md.name}  ->  {pdf_path.name}")
        render_html(md, html_path)
        html_to_pdf(html_path, pdf_path)

    shutil.rmtree(HTML_DIR, ignore_errors=True)
    print(f"\nDone. {len(md_files)} PDFs in {PDF_DIR}")


if __name__ == "__main__":
    main()
