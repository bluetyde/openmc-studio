"""run_report.py: turn a run's provenance.json record into a self-contained report.

Converts a provenance record (along with optional result summary and findings)
into a structured report dictionary, an HTML5 page, or Markdown text.
"""
import html
import math
from pathlib import Path

LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2, "not-compared": 3}


def _format_keff(nominal: float, std: float) -> str:
    """Format k-effective with 1 sigma standard deviation."""
    return f"{nominal:.5f} +/- {std:.5f} (1 sigma)"


def _val_str(val: object) -> str:
    """Format a value as text; return 'unknown' for missing, null, or empty."""
    if val is None or val == "":
        return "unknown"
    s = str(val)
    return s if s else "unknown"


def _md_cell(val: object) -> str:
    """Escape a cell value for a Markdown table: replace newlines with space, escape pipe."""
    s = str(val)
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return s.replace("|", r"\|")


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a GitHub-flavored Markdown pipe table."""
    lines = [
        "| " + " | ".join(_md_cell(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def build_report(record: dict, summary: dict | None = None, findings: list[dict] | None = None) -> dict:
    """Build a structured report dictionary from a provenance record, summary, and findings."""
    if not isinstance(record, dict):
        raise TypeError(f"record must be a dict, got {type(record).__name__}")
    if summary is not None and not isinstance(summary, dict):
        raise TypeError(f"summary must be a dict or None, got {type(summary).__name__}")
    if findings is not None:
        if not isinstance(findings, list) or not all(isinstance(f, dict) for f in findings):
            raise TypeError("findings must be a list of dicts or None")

    if "error" in record:
        err = record["error"]
        return {
            "title": "Run report (record unusable)",
            "environment": [],
            "settings": [],
            "normalization": [],
            "files": [],
            "results": [],
            "findings": [],
            "counts": {"error": 0, "warning": 0, "info": 0, "not-compared": 0},
            "notes": [f"provenance record could not be made: {err}"],
        }

    kind = record.get("kind")
    written = record.get("written")
    kind_str = str(kind) if (kind is not None and str(kind) != "") else "unknown"
    written_str = str(written) if (written is not None and str(written) != "") else "unknown"
    title = f"{kind_str} record written {written_str}"

    env = record.get("environment")
    env = env if isinstance(env, dict) else {}

    studio = env.get("studio") if isinstance(env.get("studio"), dict) else {}
    studio_ver = _val_str(studio.get("version"))

    studio_git = studio.get("git") if isinstance(studio.get("git"), dict) else {}
    commit = studio_git.get("commit")
    if not commit or str(commit).strip() == "":
        studio_commit = "unknown"
    else:
        studio_commit = str(commit)
        if studio_git.get("dirty") is True:
            studio_commit += " (uncommitted changes)"

    openmc = env.get("openmc") if isinstance(env.get("openmc"), dict) else {}
    nuclear = env.get("nuclear_data") if isinstance(env.get("nuclear_data"), dict) else {}

    env_rows = [
        ["Studio version", studio_ver],
        ["Studio commit", studio_commit],
        ["Python", _val_str(env.get("python"))],
        ["Platform", _val_str(env.get("platform"))],
        ["OpenMC (Python)", _val_str(openmc.get("python"))],
        ["OpenMC (executable)", _val_str(openmc.get("executable"))],
        ["Nuclear data file", _val_str(nuclear.get("cross_sections"))],
        ["Nuclear data SHA-256", _val_str(nuclear.get("sha256"))],
        ["Nuclear data size (bytes)", _val_str(nuclear.get("size"))],
    ]

    has_exporter = "exporter" in env or "montepy" in env or "exporter" in record or "montepy" in record
    if has_exporter:
        exp = env.get("exporter") or record.get("exporter")
        if isinstance(exp, dict):
            exp_git = exp.get("git") if isinstance(exp.get("git"), dict) else {}
            exp_commit = exp_git.get("commit") or exp.get("commit")
        else:
            exp_commit = exp
        env_rows.append(["Exporter commit", _val_str(exp_commit)])

        montepy = env.get("montepy") or record.get("montepy")
        env_rows.append(["MontePy", _val_str(montepy)])

    settings_dict = record.get("settings")
    settings_rows = []
    if isinstance(settings_dict, dict):
        for name, val in sorted(settings_dict.items(), key=lambda item: item[0]):
            settings_rows.append([str(name), _val_str(val)])

    norm_dict = record.get("normalization")
    norm_rows = []
    if isinstance(norm_dict, dict):
        for name, text in sorted(norm_dict.items(), key=lambda item: item[0]):
            norm_rows.append([str(name), _val_str(text)])

    files_dict = record.get("files")
    files_rows = []
    if isinstance(files_dict, dict):
        for name, sha in sorted(files_dict.items(), key=lambda item: item[0]):
            files_rows.append([str(name), _val_str(sha)])

    results_rows = []
    if summary is not None:
        if "run_mode" in summary:
            results_rows.append(["Run mode", _val_str(summary["run_mode"])])
        if "batches" in summary:
            results_rows.append(["Batches", _val_str(summary["batches"])])
        if "inactive" in summary:
            results_rows.append(["Inactive batches", _val_str(summary["inactive"])])
        elif "n_inactive" in summary:
            results_rows.append(["Inactive batches", _val_str(summary["n_inactive"])])
        if "particles" in summary:
            results_rows.append(["Particles per batch", _val_str(summary["particles"])])
        if "seed" in summary:
            results_rows.append(["Seed", _val_str(summary["seed"])])
        if "runtime_s" in summary:
            results_rows.append(["Runtime (s)", _val_str(summary["runtime_s"])])
        if "keff" in summary:
            keff = summary["keff"]
            if isinstance(keff, (list, tuple)) and len(keff) == 2:
                nom, std = keff[0], keff[1]
                if (
                    isinstance(nom, (int, float))
                    and isinstance(std, (int, float))
                    and math.isfinite(nom)
                    and math.isfinite(std)
                ):
                    results_rows.append(["k effective", _format_keff(float(nom), float(std))])

    counts = {"error": 0, "warning": 0, "info": 0, "not-compared": 0}
    other_count = 0
    findings_rows = []
    if findings is not None:
        for f in findings:
            lvl = f.get("level")
            if lvl in counts:
                counts[lvl] += 1
            else:
                other_count += 1
        if other_count > 0:
            counts["other"] = other_count

        sorted_findings = sorted(findings, key=lambda f: LEVEL_ORDER.get(f.get("level"), 4))
        for f in sorted_findings:
            lvl = f.get("level")
            code = f.get("code")
            msg = f.get("message")
            findings_rows.append([
                str(lvl) if lvl is not None else "unknown",
                str(code) if code is not None else "",
                str(msg) if msg is not None else "",
            ])

    notes = []
    if summary is None:
        notes.append("no result summary supplied")
    if findings is None:
        notes.append("no findings supplied")
    if studio_git.get("dirty") is True:
        notes.append("record has uncommitted changes")

    return {
        "title": title,
        "environment": env_rows,
        "settings": settings_rows,
        "normalization": norm_rows,
        "files": files_rows,
        "results": results_rows,
        "findings": findings_rows,
        "counts": counts,
        "notes": notes,
    }


def render_html(report: dict) -> str:
    """Render a report dictionary as a self-contained HTML5 page."""
    if not isinstance(report, dict):
        raise TypeError(f"report must be a dict, got {type(report).__name__}")

    title_esc = html.escape(str(report.get("title", "")), quote=True)
    out = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{title_esc}</title>",
        "<style>",
        "body { font-family: sans-serif; margin: 2rem; color: #111; }",
        "h1 { font-size: 1.8rem; margin-bottom: 1.5rem; }",
        "h2 { font-size: 1.4rem; margin-top: 2rem; margin-bottom: 0.5rem; }",
        "table { border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }",
        "th, td { border: 1px solid #ccc; padding: 0.5rem; text-align: left; vertical-align: top; }",
        "th { background: #f5f5f5; }",
        "p { margin: 0.5rem 0; }",
        "ul { margin: 0.5rem 0 1.5rem 1.5rem; }",
        "li { margin: 0.25rem 0; }",
        ".level-error { background: #fde8e8; }",
        ".level-warning { background: #fef08a; }",
        ".level-info { background: #e0f2fe; }",
        ".level-not-compared { background: #f3f4f6; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{title_esc}</h1>",
    ]

    def _render_section_table(sec_title: str, headers: list[str], rows: list[list[str]]):
        out.append(f"<h2>{html.escape(sec_title, quote=True)}</h2>")
        out.append("<table>")
        head_cells = "".join(f"<th>{html.escape(h, quote=True)}</th>" for h in headers)
        out.append(f"<thead><tr>{head_cells}</tr></thead>")
        out.append("<tbody>")
        for row in rows:
            row_cells = "".join(f"<td>{html.escape(str(cell), quote=True)}</td>" for cell in row)
            out.append(f"<tr>{row_cells}</tr>")
        out.append("</tbody></table>")

    if report.get("environment"):
        _render_section_table("Environment", ["Item", "Value"], report["environment"])

    if report.get("settings"):
        _render_section_table("Settings", ["Setting", "Value"], report["settings"])

    if report.get("normalization"):
        _render_section_table("Normalization", ["Name", "Value"], report["normalization"])

    if report.get("files"):
        _render_section_table("Files", ["File", "SHA-256"], report["files"])

    if report.get("results"):
        _render_section_table("Results", ["Metric", "Value"], report["results"])

    if report.get("findings"):
        out.append("<h2>Findings</h2>")
        counts = report.get("counts", {})
        counts_str = ", ".join(f"{k} {v}" for k, v in counts.items())
        out.append(f"<p>{html.escape(counts_str, quote=True)}</p>")
        out.append("<table>")
        out.append("<thead><tr><th>Level</th><th>Code</th><th>Message</th></tr></thead>")
        out.append("<tbody>")
        for row in report["findings"]:
            lvl = row[0] if len(row) > 0 else ""
            code = row[1] if len(row) > 1 else ""
            msg = row[2] if len(row) > 2 else ""
            lvl_esc = html.escape(str(lvl), quote=True)
            code_esc = html.escape(str(code), quote=True)
            msg_esc = html.escape(str(msg), quote=True)
            cls_esc = html.escape(f"level-{lvl}", quote=True)
            out.append(f'<tr class="{cls_esc}"><td>{lvl_esc}</td><td>{code_esc}</td><td>{msg_esc}</td></tr>')
        out.append("</tbody></table>")

    if report.get("notes"):
        out.append("<h2>Notes</h2>")
        out.append("<ul>")
        for note in report["notes"]:
            out.append(f"<li>{html.escape(str(note), quote=True)}</li>")
        out.append("</ul>")

    out.append("</body>")
    out.append("</html>")
    return "\n".join(out) + "\n"


def render_markdown(report: dict) -> str:
    """Render a report dictionary as Markdown text."""
    if not isinstance(report, dict):
        raise TypeError(f"report must be a dict, got {type(report).__name__}")

    title_clean = str(report.get("title", "")).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    out = [f"# {title_clean}"]

    if report.get("environment"):
        out.append("")
        out.append("## Environment")
        out.append("")
        out.append(_md_table(["Item", "Value"], report["environment"]))

    if report.get("settings"):
        out.append("")
        out.append("## Settings")
        out.append("")
        out.append(_md_table(["Setting", "Value"], report["settings"]))

    if report.get("normalization"):
        out.append("")
        out.append("## Normalization")
        out.append("")
        out.append(_md_table(["Name", "Value"], report["normalization"]))

    if report.get("files"):
        out.append("")
        out.append("## Files")
        out.append("")
        out.append(_md_table(["File", "SHA-256"], report["files"]))

    if report.get("results"):
        out.append("")
        out.append("## Results")
        out.append("")
        out.append(_md_table(["Metric", "Value"], report["results"]))

    if report.get("findings"):
        out.append("")
        out.append("## Findings")
        out.append("")
        counts = report.get("counts", {})
        counts_str = ", ".join(f"{k} {v}" for k, v in counts.items())
        out.append(counts_str)
        out.append("")
        out.append(_md_table(["Level", "Code", "Message"], report["findings"]))

    if report.get("notes"):
        out.append("")
        out.append("## Notes")
        out.append("")
        for note in report["notes"]:
            clean_note = str(note).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
            out.append(f"- {clean_note}")

    return "\n".join(out) + "\n"


def write(folder: Path | str, report: dict, fmt: str = "html") -> Path:
    """Write the report to <folder>/run-report.html or <folder>/run-report.md."""
    if not isinstance(report, dict):
        raise TypeError(f"report must be a dict, got {type(report).__name__}")

    if fmt == "html":
        content = render_html(report)
        target = Path(folder) / "run-report.html"
    elif fmt == "markdown":
        content = render_markdown(report)
        target = Path(folder) / "run-report.md"
    else:
        raise ValueError(f"fmt must be 'html' or 'markdown', got {fmt!r}")

    folder_path = Path(folder)
    if not folder_path.is_dir():
        raise FileNotFoundError(f"Directory not found: {folder}")

    content_bytes = content.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    target.write_bytes(content_bytes)
    return target
