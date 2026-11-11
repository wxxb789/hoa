---
name: microsoft-office
description: >-
  Create, read, edit, and template Word, PowerPoint, and Excel files offline with small Python
  CLIs. Use for reports, letters, decks, workbooks, tracked changes, comments, and CSV conversion.
  Not for legacy binary formats (.doc/.ppt/.xls), ODF files, or WYSIWYG layout work.
metadata:
  version: "0.1.39"
  areas: "work-management,software-development"
  targets: "runtime-agnostic"
  summary: "create, read, edit and template Word, PowerPoint and Excel files offline with Python CLIs"
  summary_zh: "用 Python CLI 离线创建、读取、编辑与套用 Word、PowerPoint、Excel 文件模板"
  kind: "entry"
---

# Microsoft Office Skill

Create, read, edit, and template Word (`.docx`), PowerPoint (`.pptx`), and
Excel (`.xlsx`, `.csv`) files offline with small Python CLIs built on
python-docx, python-pptx, and openpyxl. Office itself is never needed. It does
not open legacy binary formats (`.doc`, `.ppt`, `.xls`) and does not render
pages without LibreOffice.

## When to Use

Pick the format, then read its reference before working:

| File | Reference | Typical asks |
| --- | --- | --- |
| `.docx` | `references/word.md` | reports, letters, contracts, `{{token}}` templates, tracked changes, comments |
| `.pptx` | `references/powerpoint.md` | pitch decks, brand-template decks, chart refreshes, speaker notes, slide PNGs |
| `.xlsx`, `.csv` | `references/excel.md` | styled multi-sheet workbooks, formulas, charts, CSV conversion, row/column restructures |

Deeper notes: `references/revisions-and-comments.md` (Word review markup) and
`references/restructuring.md` (Excel reference shifting).

- Not for `.doc`/`.ppt`/`.xls`: convert first with
  `soffice --headless --convert-to docx|pptx|xlsx old-file` when LibreOffice is installed.
- Not for `.odt`/`.odp`/`.ods`, or WYSIWYG layout work.

## Prerequisites

- Python 3.10+ with `python-docx`, `python-pptx`, and `openpyxl` (import names
  `docx`, `pptx`, `openpyxl`).
- Pick the interpreter from a shell. Use `python` when it already imports the libraries. Otherwise
  build a shared, pinned documents environment in the user cache: it survives container restarts,
  never touches the application interpreter, and is safe to run from several agents at once. Use
  this exact block in every document skill so they all share one environment:

  ```bash
  python -c "import docx, pptx, openpyxl" 2>/dev/null && PY=python || {
    PY="${XDG_CACHE_HOME:-$HOME/.cache}/office-docs-venv/bin/python"
    "$PY" -c "import docx, openpyxl, pptx, reportlab, pypdf, pdfplumber, pypdfium2" 2>/dev/null || (
      # Safe to run from several agents at once: each caller builds a private venv,
      # a symlink publishes the first finished one atomically, the others delete theirs;
      # a published build is replaced and deleted only while it still fails to import.
      cache="${XDG_CACHE_HOME:-$HOME/.cache}"
      mkdir -p "$cache" && cd "$cache" && stage="$(mktemp -d office-docs-venv.XXXXXX)" || exit 1
      old="$(readlink office-docs-venv)"  # the published build, if any (another agent may have just published it)
      python3 -m venv "$stage" &&
        "$stage/bin/python" -m pip install -q --disable-pip-version-check python-docx==1.2.0 openpyxl==3.1.5 python-pptx==1.0.2 reportlab==5.1.0 pypdf==6.21.4 pdfplumber==0.11.10 pypdfium2==5.14.0 &&
        "$stage/bin/python" -c "import docx, openpyxl, pptx, reportlab, pypdf, pdfplumber, pypdfium2" &&
        if [ -z "$old" ]; then python3 -c 'import os, sys; os.symlink(*sys.argv[1:])' "$stage" office-docs-venv
        elif [ "$(readlink office-docs-venv)" = "$old" ] && ! "$old/bin/python" -c "import docx, openpyxl, pptx, reportlab, pypdf, pdfplumber, pypdfium2" 2>/dev/null; then
          ln -s "$stage" "$stage.lnk" && python3 -c 'import os, sys; os.replace(*sys.argv[1:])' "$stage.lnk" office-docs-venv &&
            case "$old" in office-docs-venv.??????) rm -rf "$old" ;; esac
        fi 2>/dev/null
      [ "$(readlink office-docs-venv)" = "$stage" ] || rm -rf "$stage" "$stage.lnk"
    )
  }
  export PY
  "$PY" scripts/docx_create.py --help
  ```

  Run every helper with `"$PY"`. If the host already provides a pinned documents environment
  manager, use the interpreter it prints instead of building the cache venv; never
  `pip install` into the interpreter that runs the host application or the one that manager owns.

- Optional: LibreOffice (`soffice`) for PDF export, Excel recalculation, and
  slide rendering, plus poppler (`pdftoppm` or `pdftocairo`) for slide PNGs.
  The helpers that need them report what is missing and exit 0.

## How to Run

Every helper lives in `scripts/`, is an argparse CLI with `--help`, prints
JSON to stdout, and exits non-zero on failure. Run them from the skill
directory. Author JSON specs with your file-writing tool; read results from
stdout or the output files.

```bash
"$PY" scripts/docx_create.py spec.json out.docx
"$PY" scripts/pptx_create.py deck.json out.pptx
"$PY" scripts/xlsx_create.py spec.json report.xlsx
```

## Quick Reference

| Task | Word | PowerPoint | Excel |
| --- | --- | --- | --- |
| Create from JSON spec | `docx_create.py` | `pptx_create.py` | `xlsx_create.py`, `csv_to_xlsx.py` |
| Read back | `docx_read.py --text/--structure` | `pptx_read.py --outline` | `xlsx_read.py --sheets/--json` |
| Edit | `docx_edit.py` | `pptx_edit.py` | `xlsx_edit.py`, `xlsx_restructure.py` |
| Fill a template | `docx_template.py` | `pptx_from_template.py` | — |
| Review / check | `docx_revisions.py`, `docx_comments.py`, `docx_validate.py` | `pptx_render.py` (slide PNGs) | `xlsx_recalc.py`, `xlsx_to_csv.py` |

The per-format reference has the full flag table.

## Procedure

1. Identify the format from the file extension or the ask, and read its
   reference (`references/<format>.md`).
2. Set `PY` with the Prerequisites block once per session.
3. Create, edit, or read with that format's helpers; pass an output path to
   keep the original whenever the helper supports one.
4. Verify the result as the reference's Verification section says, then give
   the user the exact output path.

## Converting to PDF

When LibreOffice is installed, convert headlessly:

```bash
soffice --headless --convert-to pdf --outdir out/ file.docx   # also .pptx, .xlsx
soffice --headless --convert-to csv --outdir out/ report.xlsx # first sheet only
```

Check first with `command -v soffice || command -v libreoffice`. Fonts not on
the host are substituted, so render-check decks before shipping. There is no
pure-Python path to PDF for any of these formats: if `soffice` is missing, say
so rather than approximating. For other sheets use
`xlsx_to_csv.py --sheet NAME`.

## Pitfalls

- **Never unzip-and-edit the XML.** These files are zip packages; raw text
  substitution corrupts them. Edit through the helpers (or the libraries) and
  edit only the JSON inputs with a text editor.
- **Text is split into runs.** Word and PowerPoint fragment text at edit
  boundaries; the replace helpers merge equal-format runs first, but a match
  across differently formatted runs takes the first run's formatting.
- **Nothing computes fields or formulas.** Word TOC/page fields and Excel
  formulas are filled in by the office app on open (or by `xlsx_recalc.py`).
- **Encoding.** Write specs as UTF-8; the helpers read UTF-8 explicitly.
- Format-specific traps are in each reference.

## Verification

- Re-read every output with the format's read helper and check the expected
  content is there and the old content is gone.
- Word: `docx_validate.py out.docx` exits 0 after revision, comment, or field
  surgery.
- PowerPoint: render with `pptx_render.py` and inspect each PNG with an
  image-capable model or viewer when the render tools exist.
- Excel: `xlsx_read.py --formulas` lists written formulas; run
  `xlsx_recalc.py` when cached values matter.
