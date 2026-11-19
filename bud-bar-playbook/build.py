#!/usr/bin/env python3
"""
Rebuild the Bud Bar Business Playbook SCORM 1.2 packages from /content.

    python build.py              # bump both versions, rebuild, zip, validate
    python build.py --no-bump    # rebuild without changing version numbers
    python build.py free         # rebuild only one course (free | paid-sample)

Uses only the Python standard library (Python 3.8+). Nothing to install.
"""
import argparse
import datetime
import html
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
ENGINE = ROOT / "engine"
BRAND = ROOT / "brand"
COURSES = ["free", "paid-sample"]

VERIFY_RE = re.compile(r"\[PHILIP TO VERIFY[^\]]*\]")
EMBED_RE = re.compile(r"^\[\[([a-z-]+):([^|\]]+)(?:\|([^\]]+))?\]\]$")


class BuildError(Exception):
    pass


# ---------------------------------------------------------------------------
# Small Markdown converter (headings, paragraphs, lists, tables, callouts,
# **bold**, *italic*, [links](url), and [PHILIP TO VERIFY] highlights)
# ---------------------------------------------------------------------------
def inline(text):
    out = html.escape(text, quote=False)

    def link(m):
        label, url = m.group(1), m.group(2).replace('"', "%22")
        if url.startswith(("http://", "https://")):
            return (f'<a href="{url}" target="_blank" rel="noopener">{label}'
                    f'<span class="sr-only"> (opens in a new tab)</span></a>')
        return f'<a href="{url}">{label}</a>'

    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])", r"<em>\1</em>", out)
    out = VERIFY_RE.sub(lambda m: f'<mark class="verify">{m.group(0)}</mark>', out)
    return out


def strip_tags(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s))


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def render_table(rows):
    head = split_row(rows[0])
    body = [split_row(r) for r in rows[1:] if not re.match(r"^\|?\s*:?-{2,}", r.strip())]
    h = "".join(f'<th scope="col">{inline(c)}</th>' for c in head)
    b = ""
    for r in body:
        cells = "".join(
            (f'<th scope="row">{inline(c)}</th>' if i == 0 else f"<td>{inline(c)}</td>")
            for i, c in enumerate(r))
        b += f"<tr>{cells}</tr>"
    return f'<div class="table-wrap"><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def is_block_start(s):
    return (s.startswith(("### ", "> ", "|")) or re.match(r"^[-*] ", s)
            or re.match(r"^\d+\. ", s) or EMBED_RE.match(s))


def render_screen_body(lines, ctx, where):
    """Turn one screen's Markdown lines into a list of blocks for the player."""
    blocks, buf = [], []

    def flush():
        if buf:
            blocks.append({"html": "".join(buf)})
            buf.clear()

    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        m = EMBED_RE.match(s)
        if m:
            flush()
            blocks.append(handle_embed(m.group(1), m.group(2).strip(), m.group(3), ctx, where))
            i += 1
        elif s.startswith("### "):
            buf.append(f"<h2>{inline(s[4:])}</h2>")
            i += 1
        elif s.startswith(">"):
            parts = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                parts.append(lines[i].strip().lstrip(">").strip())
                i += 1
            buf.append(f'<div class="callout"><p>{inline(" ".join(parts))}</p></div>')
        elif s.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            buf.append(render_table(rows))
        elif re.match(r"^([-*]|\d+\.) ", s):
            ordered = bool(re.match(r"^\d+\. ", s))
            pat = r"^\d+\. " if ordered else r"^[-*] "
            items = []
            while i < len(lines):
                t = lines[i].strip()
                if re.match(pat, t):
                    items.append(re.sub(pat, "", t))
                elif t and not is_block_start(t) and items:
                    items[-1] += " " + t          # wrapped continuation line
                else:
                    break
                i += 1
            tag = "ol" if ordered else "ul"
            buf.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not is_block_start(lines[i].strip()):
                para.append(lines[i].strip())
                i += 1
            buf.append(f"<p>{inline(' '.join(para))}</p>")
    flush()
    return blocks


# ---------------------------------------------------------------------------
# Embeds: [[calculator:file.json]] [[quiz:file.json]] [[state-table:file.json]]
#         [[download:file.json|Link text]]
# ---------------------------------------------------------------------------
def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BuildError(f"File not found: {path.relative_to(ROOT)}")
    except json.JSONDecodeError as e:
        raise BuildError(f"{path.relative_to(ROOT)} is not valid JSON (line {e.lineno}, column {e.colno}): {e.msg}")


def handle_embed(kind, fname, label, ctx, where):
    path = ctx["dir"] / fname
    data = load_json(path)
    rel = path.relative_to(ROOT)

    if kind == "quiz":
        qs = data.get("questions") or []
        if not qs:
            raise BuildError(f"{rel}: no questions found")
        out = []
        for n, q in enumerate(qs, 1):
            opts = q.get("options") or []
            ans = q.get("answer")
            if len(opts) < 2:
                raise BuildError(f"{rel}: question {n} needs at least 2 options")
            if not isinstance(ans, int) or not 1 <= ans <= len(opts):
                raise BuildError(f"{rel}: question {n} has answer {ans!r}; it must be a number from 1 to {len(opts)}")
            out.append({"q_html": inline(q["question"]), "options_html": [inline(o) for o in opts],
                        "answer": ans - 1, "feedback_html": inline(q.get("feedback", ""))})
        ctx["quiz_count"] += 1
        return {"embed": "quiz", "data": {"questions": out}}

    if kind == "calculator":
        needed = {"guests", "hours", "staff", "hourly_rate", "per_guest_fee", "staff_pay",
                  "setup_hours", "supplies_per_guest", "other_costs"}
        ids = {f["id"] for f in data["inputs"]}
        if ids != needed:
            raise BuildError(f"{rel}: input ids must be exactly {sorted(needed)} "
                             f"(you can change labels and defaults, not ids). Missing: {sorted(needed - ids)}; "
                             f"unknown: {sorted(ids - needed)}")
        return {"embed": "calculator", "data": {
            "note_html": inline(data["note"]),
            "event_heading_html": inline(data.get("event_heading", "One event")),
            "startup_heading_html": inline(data.get("startup_heading", "Startup costs")),
            "inputs": [{"id": f["id"], "label_html": inline(f["label"]), "default": f["default"],
                        "money": bool(f.get("money")), "step": f.get("step", 1)} for f in data["inputs"]],
            "startup_costs": [{"label_html": inline(c["label"]), "default": c["default"]}
                              for c in data["startup_costs"]],
        }}

    if kind == "state-table":
        cols = data["columns"]
        head = "".join(f'<th scope="col">{inline(c)}</th>' for c in cols)
        rows = "".join(
            f'<tr><th scope="row">{inline(s["state"])}</th><td>{inline(s["status"])}</td>'
            f'<td>{inline(s.get("notes", ""))}</td></tr>' for s in data["states"])
        return {"html": f'<p>{inline(data.get("list_note", ""))}</p>'
                        f'<div class="table-wrap"><table class="state-table"><thead><tr>{head}</tr></thead>'
                        f'<tbody>{rows}</tbody></table></div>'}

    if kind == "download":
        out_name = Path(fname).stem + ".html"
        (ctx["out"] / "downloads").mkdir(exist_ok=True)
        (ctx["out"] / "downloads" / out_name).write_text(render_form(data, ctx["cfg"]), encoding="utf-8")
        text = inline(label or data.get("title", "Download"))
        return {"html": f'<p class="download"><a class="btn btn-primary" href="downloads/{out_name}" '
                        f'target="_blank" rel="noopener">{text}<span class="sr-only"> (opens in a new tab)</span></a></p>'}

    raise BuildError(f"{where}: unknown embed [[{kind}:...]] (use quiz, calculator, state-table, or download)")


def render_form(data, cfg):
    """Printable, fillable HTML form (e.g. the Client Event Intake Form)."""
    fid = 0
    sections = ""
    for sec in data["sections"]:
        fields = ""
        for f in sec["fields"]:
            fid += 1
            t = f.get("type", "text")
            lab = inline(f["label"])
            if t == "checkboxes":
                opts = "".join(f'<label class="cb"><input type="checkbox" name="f{fid}"> {inline(o)}</label>'
                               for o in f["options"])
                fields += f'<fieldset class="f"><legend>{lab}</legend><div class="cbs">{opts}</div></fieldset>'
            elif t == "textarea":
                fields += f'<div class="f wide"><label for="f{fid}">{lab}</label><textarea id="f{fid}" rows="3"></textarea></div>'
            elif t == "signature":
                fields += f'<div class="f"><label for="f{fid}">{lab}</label><input id="f{fid}" type="text" class="sig"></div>'
            else:
                fields += f'<div class="f"><label for="f{fid}">{lab}</label><input id="f{fid}" type="{t}"></div>'
        sections += f'<section><h2>{inline(sec["heading"])}</h2><div class="grid">{fields}</div></section>'
    title = html.escape(data["title"])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="../brand/brand.css">
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text-body);font-family:var(--font-body);line-height:1.5}}
main{{max-width:820px;margin:0 auto;padding:1.5rem 1rem 3rem}}
h1,h2{{font-family:var(--font-display);color:var(--text-heading)}}
h1{{margin:.2rem 0 .3rem}} h2{{font-size:1.15rem;border-bottom:2px solid var(--border-rosegold);padding-bottom:.2rem;margin:1.6rem 0 .8rem}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:.8rem 1.2rem}}
.f{{margin:0;border:0;padding:0;min-width:0}} .f.wide{{grid-column:1/-1}}
.f label,.f legend{{display:block;font-size:.9rem;font-weight:600;color:var(--text-heading);margin-bottom:.2rem;padding:0}}
input[type=text],input[type=email],input[type=tel],input[type=date],input[type=time],input[type=number],textarea{{width:100%;font:inherit;color:var(--text-heading);background:#fff;border:1px solid var(--border-rosegold);border-radius:6px;padding:.4rem .5rem;min-height:40px}}
.sig{{border-width:0 0 2px!important;border-radius:0!important;background:transparent!important}}
.cbs{{display:flex;flex-wrap:wrap;gap:.3rem 1rem}} .cb{{font-weight:400!important;display:inline-flex!important;gap:.35rem;align-items:center}}
.cb input{{width:1.1rem;height:1.1rem;accent-color:var(--accent)}}
.bar{{display:flex;justify-content:space-between;align-items:center;gap:1rem;flex-wrap:wrap}}
button{{font:inherit;font-weight:600;background:var(--accent);color:var(--on-accent);border:0;border-radius:var(--radius);padding:.55rem 1.1rem;min-height:44px;cursor:pointer}}
:focus-visible{{outline:3px solid var(--focus);outline-offset:2px}}
mark.verify{{background:var(--verify-bg);color:var(--verify-text);font-weight:700;font-size:.85em}}
.foot{{margin-top:2rem;font-size:.85rem}}
@media print{{body{{background:#fff}} button{{display:none}} main{{padding:0}} section{{break-inside:avoid}} input,textarea{{border-color:#999}}}}
</style>
</head>
<body>
<main>
<div class="bar"><div><h1>{title}</h1><p>{inline(data.get("intro", ""))}</p></div>
<button type="button" onclick="window.print()">Print or save as PDF</button></div>
<form onsubmit="return false">{sections}</form>
<p class="foot">{inline(data.get("footer", ""))}<br>{html.escape(cfg["title"])} · v{html.escape(cfg["version"])}</p>
</main>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------
def parse_module(path, ctx):
    if not path.exists():
        raise BuildError(f"Module file listed in course.json not found: {path.relative_to(ROOT)}")
    title, screens, cur = None, [], None
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("# ") and title is None and cur is None:
            title = line[2:].strip()
        elif line.startswith("## "):
            cur = {"title": line[3:].strip(), "lines": [], "line": n}
            screens.append(cur)
        elif cur is None:
            if line.strip():
                raise BuildError(f"{path.relative_to(ROOT)} line {n}: text must come after a '## Screen title' line")
        else:
            cur["lines"].append(line)
    rel = path.relative_to(ROOT)
    if not title:
        raise BuildError(f"{rel}: the first line must be '# Module title'")
    if not screens:
        raise BuildError(f"{rel}: no screens found (each screen starts with '## Screen title')")
    return {
        "id": path.stem,
        "title": title,
        "screens": [{"title_html": inline(s["title"]),
                     "blocks": render_screen_body(s["lines"], ctx, f"{rel} line {s['line']}")}
                    for s in screens],
    }


# ---------------------------------------------------------------------------
# Manifest, zip, validation
# ---------------------------------------------------------------------------
def make_manifest(cfg, files):
    mastery = ""
    if cfg["completion"] == "quiz" and cfg.get("passing_score") is not None:
        mastery = f"\n        <adlcp:masteryscore>{int(cfg['passing_score'])}</adlcp:masteryscore>"
    title = xml_escape(f"{cfg['title']} (v{cfg['version']})")
    file_lines = "\n".join(f'      <file href="{xml_escape(f)}"/>' for f in files)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{cfg['id']}" version="{cfg['version']}"
  xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
  xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.imsproject.org/xsd/imscp_rootv1p1p2 imscp_rootv1p1p2.xsd http://www.imsglobal.org/xsd/imsmd_rootv1p2p1 imsmd_rootv1p2p1.xsd http://www.adlnet.org/xsd/adlcp_rootv1p2 adlcp_rootv1p2.xsd">
  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>1.2</schemaversion>
  </metadata>
  <organizations default="ORG-1">
    <organization identifier="ORG-1">
      <title>{title}</title>
      <item identifier="ITEM-1" identifierref="RES-1" isvisible="true">
        <title>{title}</title>{mastery}
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="RES-1" type="webcontent" adlcp:scormtype="sco" href="index.html">
{file_lines}
    </resource>
  </resources>
</manifest>
"""


def validate_zip(zip_path, cfg):
    """Check the zip the way an LMS importer would. Raises BuildError on problems."""
    CP = "{http://www.imsproject.org/xsd/imscp_rootv1p1p2}"
    AD = "{http://www.adlnet.org/xsd/adlcp_rootv1p2}"
    errors = []
    with zipfile.ZipFile(zip_path) as z:
        bad = z.testzip()
        if bad:
            errors.append(f"corrupt file in zip: {bad}")
        names = set(n for n in z.namelist() if not n.endswith("/"))
        if "imsmanifest.xml" not in names:
            raise BuildError(f"{zip_path.name}: imsmanifest.xml is not at the root of the zip")
        try:
            root = ET.fromstring(z.read("imsmanifest.xml"))
        except ET.ParseError as e:
            raise BuildError(f"{zip_path.name}: imsmanifest.xml is not well-formed XML: {e}")

    if root.tag != CP + "manifest":
        errors.append("root element must be <manifest> in the IMS CP 1.1.2 namespace")
    if root.get("version") != cfg["version"]:
        errors.append("manifest version attribute does not match course.json")
    if (root.findtext(f"{CP}metadata/{CP}schema") or "").strip() != "ADL SCORM":
        errors.append("<metadata><schema> must be 'ADL SCORM'")
    if (root.findtext(f"{CP}metadata/{CP}schemaversion") or "").strip() != "1.2":
        errors.append("<metadata><schemaversion> must be '1.2'")
    orgs = root.find(f"{CP}organizations")
    org_ids = [o.get("identifier") for o in orgs.findall(f"{CP}organization")] if orgs is not None else []
    if orgs is None or orgs.get("default") not in org_ids:
        errors.append("organizations/@default must match an organization identifier")
    res_ids = {r.get("identifier"): r for r in root.iter(CP + "resource")}
    all_ids = org_ids + [i.get("identifier") for i in root.iter(CP + "item")] + list(res_ids)
    if len(all_ids) != len(set(all_ids)):
        errors.append("identifiers must be unique")
    listed = set()
    for item in root.iter(CP + "item"):
        ref = item.get("identifierref")
        if ref and ref not in res_ids:
            errors.append(f"item {item.get('identifier')} points to missing resource {ref}")
        ms = item.find(AD + "masteryscore")
        if ms is not None:
            txt = (ms.text or "").strip()
            if not txt.isdigit() or not 0 <= int(txt) <= 100:
                errors.append("masteryscore must be a whole number from 0 to 100")
    for rid, r in res_ids.items():
        if r.get(AD + "scormtype") not in ("sco", "asset"):
            errors.append(f"resource {rid} needs adlcp:scormtype='sco' or 'asset'")
        if r.get("href") not in names:
            errors.append(f"resource {rid} launch file {r.get('href')} is not in the zip")
        for f in r.findall(CP + "file"):
            listed.add(f.get("href"))
            if f.get("href") not in names:
                errors.append(f"manifest lists {f.get('href')} but it is not in the zip")
    unlisted = names - listed - {"imsmanifest.xml"}
    if unlisted:
        errors.append(f"files in zip not listed in manifest: {sorted(unlisted)}")
    if errors:
        raise BuildError(f"{zip_path.name} failed validation:\n  - " + "\n  - ".join(errors))
    return len(names)


# ---------------------------------------------------------------------------
# Build one course
# ---------------------------------------------------------------------------
def bump(version):
    parts = version.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def build_course(key, do_bump):
    cdir = CONTENT / key
    cfg_path = cdir / "course.json"
    cfg = load_json(cfg_path)
    for k in ("id", "title", "short_title", "version", "package_folder", "zip_name", "completion", "modules"):
        if k not in cfg:
            raise BuildError(f"{cfg_path.relative_to(ROOT)} is missing \"{k}\"")
    if cfg["completion"] not in ("quiz", "end"):
        raise BuildError(f"{cfg_path.relative_to(ROOT)}: completion must be \"quiz\" or \"end\"")
    if cfg["completion"] == "quiz" and not cfg.get("passing_score"):
        raise BuildError(f"{cfg_path.relative_to(ROOT)}: completion \"quiz\" needs a passing_score")

    old_version = cfg["version"]
    if do_bump:
        cfg["version"] = bump(cfg["version"])

    # Build into a temporary folder; the real folder and zip are only replaced
    # once everything succeeds, so a typo never breaks the last good package.
    final_out = ROOT / cfg["package_folder"]
    out = ROOT / (".building-" + cfg["package_folder"])
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()

    ctx = {"dir": cdir, "out": out, "cfg": cfg, "quiz_count": 0}
    modules = [parse_module(cdir / m, ctx) for m in cfg["modules"]]
    if cfg["completion"] == "quiz" and ctx["quiz_count"] != 1:
        raise BuildError(f"{key}: a course with completion \"quiz\" needs exactly one [[quiz:...]] (found {ctx['quiz_count']})")

    built = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    data = {
        "id": cfg["id"], "title": cfg["title"], "version": cfg["version"], "built": built,
        "completion": cfg["completion"], "passing_score": cfg.get("passing_score"), "modules": modules,
    }
    (out / "course-data.js").write_text(
        "/* GENERATED by build.py from /content — do not edit; edit the content files instead. */\n"
        "window.COURSE_DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")

    (out / "engine").mkdir()
    for f in ("scorm-api.js", "debug-panel.js", "player.js", "player.css"):
        shutil.copy2(ENGINE / f, out / "engine" / f)
    shutil.copytree(BRAND, out / "brand")
    logo = cfg.get("logo_file", "logo.svg")
    if not (BRAND / logo).exists():
        raise BuildError(f"Logo file brand/{logo} not found")
    page = (ENGINE / "index.html").read_text(encoding="utf-8")
    page = (page.replace("{{TITLE}}", html.escape(cfg["title"]))
                .replace("{{SHORT_TITLE}}", html.escape(cfg["short_title"]))
                .replace("{{LOGO}}", html.escape(logo)))
    (out / "index.html").write_text(page, encoding="utf-8")

    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    (out / "imsmanifest.xml").write_text(make_manifest(cfg, files), encoding="utf-8")

    zip_path = ROOT / cfg["zip_name"]
    tmp_zip = ROOT / (".building-" + cfg["zip_name"])
    with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(out).as_posix())
    try:
        count = validate_zip(tmp_zip, cfg)
    except BuildError:
        tmp_zip.unlink()
        raise
    tmp_zip.replace(zip_path)
    if final_out.exists():
        shutil.rmtree(final_out)
    out.rename(final_out)

    # Only save the bumped version once everything succeeded.
    if do_bump:
        text = cfg_path.read_text(encoding="utf-8")
        text = re.sub(r'("version"\s*:\s*")' + re.escape(old_version) + '"', r"\g<1>" + cfg["version"] + '"', text, count=1)
        cfg_path.write_text(text, encoding="utf-8")

    screens = sum(len(m["screens"]) for m in modules)
    print(f"  {key}: v{cfg['version']} · {len(modules)} modules · {screens} screens · "
          f"{count} files → {zip_path.name} (manifest OK)")


def write_verify_list():
    rows = []
    for f in sorted(CONTENT.rglob("*")):
        if f.suffix not in (".md", ".json") or not f.is_file():
            continue
        where = ""
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if f.suffix == ".md" and line.startswith("## "):
                where = line[3:].strip()
            if f.name == "state-table.json":
                m = re.search(r'"state":\s*"([^"]+)"', line)
                if m:
                    where = m.group(1)
            if VERIFY_RE.search(line):
                text = line.strip().rstrip(",")
                rows.append((f.relative_to(ROOT).as_posix(), n, where, text))
    out = ["# [PHILIP TO VERIFY] checklist", "",
           "Generated by `python build.py` from every file in `content/`. "
           "Fix the wording in the content file, remove the marker, and rebuild. "
           "This list regenerates each build, so finished items disappear.", "",
           f"**{len(rows)} items**", ""]
    current = None
    for path, n, where, text in rows:
        if path != current:
            out += ["", f"## `{path}`", ""]
            current = path
        loc = f"line {n}" + (f" — *{where}*" if where else "")
        out.append(f"- [ ] {loc}: {text}")
    (ROOT / "VERIFY_LIST.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description="Rebuild the SCORM 1.2 packages from /content.")
    ap.add_argument("courses", nargs="*", help="which course(s) to build: free, paid-sample (default: both)")
    ap.add_argument("--no-bump", action="store_true", help="do not increase the version numbers")
    args = ap.parse_args()
    targets = args.courses or COURSES
    for t in targets:
        if t not in COURSES:
            ap.error(f"unknown course '{t}' (choose from: {', '.join(COURSES)})")
    print("Building SCORM 1.2 packages...")
    try:
        for key in targets:
            build_course(key, not args.no_bump)
        n = write_verify_list()
    except BuildError as e:
        for tmp in ROOT.glob(".building-*"):
            shutil.rmtree(tmp) if tmp.is_dir() else tmp.unlink()
        print(f"\nBUILD FAILED: {e}", file=sys.stderr)
        print("Nothing was changed: the previous packages and version numbers are still in place.", file=sys.stderr)
        sys.exit(1)
    print(f"  VERIFY_LIST.md: {n} [PHILIP TO VERIFY] items")
    print("Done.")


if __name__ == "__main__":
    main()
