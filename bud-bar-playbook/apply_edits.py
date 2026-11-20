#!/usr/bin/env python3
"""
Copy edits made on the online preview pages back into /content.

    python apply_edits.py edits.json          # apply, then run: python build.py
    python apply_edits.py edits.json --check  # show what would change, change nothing

edits.json is an export of the preview page's "edits" store (Claude makes it
when you say "apply my edits"). Each edit replaces one screen's title and text
in its Markdown file. Interactive pieces ([[quiz:...]], [[calculator:...]],
etc.) are kept exactly as they were. Text blocks you did not change keep their
original Markdown byte for byte.
"""
import argparse
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build  # noqa: E402  (reuses the exact Markdown -> HTML rules)


# ---------------------------------------------------------------------------
# HTML (from the page editor) -> Markdown (the content file format)
# ---------------------------------------------------------------------------
class ToMarkdown(HTMLParser):
    BLOCKS = {"p", "div", "h2", "ul", "ol", "li", "table", "thead", "tbody", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []          # finished Markdown blocks
        self.buf = ""          # current inline text
        self.kind = None       # 'p', 'h2', 'callout'
        self.lists = []        # stack of ['ul'|'ol', counter]
        self.items = []        # finished list lines for the current list
        self.links = []        # stack of hrefs
        self.skip = 0          # inside <span class="sr-only">
        self.table = None      # list of rows (list of cells)
        self.cell = None
        self.opened = None     # a ** or * marker that has no text after it yet

    # -- helpers
    def flush(self):
        text = re.sub(r"\s+", " ", self.buf).strip()
        self.buf = ""
        if not text:
            return
        if self.table is not None and self.cell is not None:
            self.cell.append(text)
        elif self.lists:
            kind, _ = self.lists[-1]
            self.lists[-1][1] += 1
            marker = f"{self.lists[-1][1]}." if kind == "ol" else "-"
            self.items.append(f"{marker} {text}")
        elif self.kind == "h2":
            self.out.append(f"### {text}")
        elif self.kind == "callout":
            self.out.append(f"> {text}")
        else:
            self.out.append(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "span" and "sr-only" in cls:
            self.skip += 1
            return
        if tag in ("ul", "ol"):
            self.flush()
            self.lists.append([tag, 0])
        elif tag == "li":
            self.flush()
        elif tag == "table":
            self.flush()
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.table.append([])
        elif tag in ("td", "th") and self.table is not None:
            self.cell = []
        elif tag in ("p", "div", "h2"):
            self.flush()
            if tag == "h2":
                self.kind = "h2"
            elif "callout" in cls:
                self.kind = "callout"
            elif self.kind != "callout":
                self.kind = "p"
        elif tag == "br":
            self.buf += " "
        elif tag in ("strong", "em"):
            self.opened = "**" if tag == "strong" else "*"
            self.buf += self.opened
        elif tag == "a":
            self.links.append(a.get("href", ""))
            self.buf += "["

    def handle_endtag(self, tag):
        if tag == "span" and self.skip:
            self.skip -= 1
            return
        if tag in ("strong", "em"):
            mark = "**" if tag == "strong" else "*"
            if self.opened == mark and self.buf.endswith(mark):
                self.buf = self.buf[:-len(mark)]          # empty <strong></strong>
            else:
                core = self.buf.rstrip()
                self.buf = core + mark + self.buf[len(core):]   # keep trailing spaces outside
            self.opened = None
        elif tag == "a" and self.links:
            href = self.links.pop()
            self.buf += f"]({href})" if href else "]"
        elif tag == "li":
            self.flush()
        elif tag in ("ul", "ol"):
            self.flush()
            self.lists.pop()
            if not self.lists and self.items:
                self.out.append("\n".join(self.items))
                self.items = []
        elif tag in ("td", "th") and self.table is not None:
            self.flush()
            if self.table:
                self.table[-1].append(" ".join(self.cell or []).replace("|", "/"))
            self.cell = None
        elif tag == "table" and self.table is not None:
            rows = [r for r in self.table if r]
            self.table = None
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
                lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                self.out.append("\n".join(lines))
        elif tag in ("p", "h2", "div"):
            self.flush()
            self.kind = None

    def handle_data(self, data):
        if self.skip:
            return
        if self.opened and self.buf.endswith(self.opened):
            lead = data[:len(data) - len(data.lstrip())]
            if lead:   # "<strong> word" -> " **word"
                self.buf = self.buf[:-len(self.opened)] + " " + self.opened
                data = data.lstrip()
            if data:
                self.opened = None
        self.buf += data

    def result(self):
        self.flush()
        if self.items:
            self.out.append("\n".join(self.items))
        md = "\n\n".join(b for b in self.out if b.strip())
        md = md.replace("** **", " ").replace("****", "")
        return md


def html_to_md(fragment):
    p = ToMarkdown()
    p.feed(fragment or "")
    p.close()
    return p.result()


def title_to_md(fragment):
    return html_to_md(f"<p>{fragment}</p>").replace("\n", " ").strip()


# ---------------------------------------------------------------------------
# Locate a screen in its Markdown file and rebuild it
# ---------------------------------------------------------------------------
def screen_spans(lines):
    """[(start_line_index, end_line_index_exclusive, title)] for each '## ' screen."""
    starts = [i for i, l in enumerate(lines) if l.startswith("## ")]
    return [(s, (starts[n + 1] if n + 1 < len(starts) else len(lines)), lines[s][3:].strip())
            for n, s in enumerate(starts)]


def body_segments(body_lines):
    """Split a screen body the same way build.py does: text chunks and embed lines."""
    segs, chunk = [], []
    for line in body_lines:
        if build.EMBED_RE.match(line.strip()):
            if any(l.strip() for l in chunk):
                segs.append(("text", chunk))
            segs.append(("embed", [line.strip()]))
            chunk = []
        else:
            chunk.append(line)
    if any(l.strip() for l in chunk):
        segs.append(("text", chunk))
    return segs


def strip_tags(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def normalize(h):
    """Compare built HTML and editor HTML loosely (the browser reformats a little)."""
    h = re.sub(r'\s(target|rel)="[^"]*"', "", h or "")
    h = re.sub(r"\s+", " ", h).replace("&nbsp;", " ")
    return h.strip()


def course_dirs():
    out = {}
    for d in sorted((ROOT / "content").iterdir()):
        cfg = d / "course.json"
        if cfg.exists():
            out[json.loads(cfg.read_text(encoding="utf-8"))["id"]] = d
    return out


def load_edits(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    found = []

    def walk(x):
        if isinstance(x, dict):
            if "key" in x and "blocks" in x and "course" in x:
                found.append(x)
            else:
                for v in x.values():
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(raw)
    return found


def apply(edits, check=False):
    dirs = course_dirs()
    changed, problems = [], []
    by_file = {}
    for e in edits:
        d = dirs.get(e["course"])
        if not d:
            problems.append(f"{e['key']}: unknown course {e['course']}")
            continue
        by_file.setdefault(d / e["file"], []).append(e)

    for path, file_edits in by_file.items():
        if not path.exists():
            problems.append(f"{path.relative_to(ROOT)}: file not found")
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        spans = screen_spans(lines)
        # Apply from the bottom up so earlier line numbers stay valid.
        for e in sorted(file_edits, key=lambda x: -int(x["screen"])):
            idx = int(e["screen"])
            if idx >= len(spans):
                problems.append(f"{e['key']}: screen {idx + 1} no longer exists in {path.name}")
                continue
            start, end, title = spans[idx]
            if strip_tags(build.inline(title)) != strip_tags(e.get("original_title", "")):
                problems.append(f"{e['key']}: screen title in {path.name} changed since the edit "
                                f"(file: '{title}', edit made on: '{e.get('original_title')}'); skipped")
                continue
            segs = body_segments(lines[start + 1:end])
            new_body, ti = [], 0
            blocks = e.get("blocks") or []
            for bi, (kind, seg) in enumerate(segs):
                if kind == "embed":
                    new_body.append(seg[0])
                    continue
                edited = blocks[bi] if bi < len(blocks) else None
                original_html = build.render_screen_body(seg, {}, path.name)[0]["html"]
                if edited is None or normalize(edited) == normalize(original_html):
                    new_body.append("\n".join(seg).strip("\n"))
                else:
                    md = html_to_md(edited)
                    if md:
                        new_body.append(md)
            new_title = title_to_md(e["title_html"]) or title
            screen_md = [f"## {new_title}", ""] + "\n\n".join(new_body).split("\n") + [""]
            if lines[start:end] != screen_md and "\n".join(lines[start:end]).strip() != "\n".join(screen_md).strip():
                lines[start:end] = screen_md
                changed.append(f"{path.relative_to(ROOT)} · screen {idx + 1} ({new_title})")
        if not check:
            path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    return changed, problems


def main():
    ap = argparse.ArgumentParser(description="Apply preview-page edits to /content.")
    ap.add_argument("edits_json")
    ap.add_argument("--check", action="store_true", help="report only; change nothing")
    args = ap.parse_args()
    edits = load_edits(args.edits_json)
    changed, problems = apply(edits, args.check)
    print(f"{len(edits)} saved edit(s) found.")
    for c in changed:
        print(("  would update " if args.check else "  updated ") + c)
    for p in problems:
        print("  ! " + p)
    if not changed:
        print("  No content changes.")
    elif not args.check:
        print("Now run: python build.py")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
