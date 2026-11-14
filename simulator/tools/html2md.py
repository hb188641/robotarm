"""Minimal stdlib HTML -> Markdown converter for Sphinx (Furo) doc pages.

Usage: python3 -I html2md.py <input.html> <output.md> [base_url]
Only the <article role="main"> content is converted.
"""

import html
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urljoin

SKIP_TAGS = {"script", "style", "nav", "button", "svg", "form"}
VOID = {"img", "br", "hr", "meta", "link", "input", "source", "wbr"}


class Converter(HTMLParser):
    def __init__(self, base_url=""):
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.out = []  # finished markdown chunks
        self.buf = []  # current inline buffer
        self.in_main = 0  # depth inside <article role=main>
        self.skip = 0  # depth inside skipped elements
        self.pre = 0
        self.lists = []  # stack of ["ul"|"ol", counter]
        self.quote = 0  # admonition depth
        self.stack = []  # open tags (to track main/skip depth)
        self.link = None
        self.table = None  # list of rows; row = list of cells
        self.cell = None

    # ---- helpers ----
    def flush(self, prefix=""):
        text = "".join(self.buf)
        self.buf = []
        if self.pre:
            return
        text = re.sub(r"[ \t\r\n]+", " ", text).strip()
        if not text:
            return
        self.emit(prefix + text)

    def emit(self, block):
        if self.quote:
            block = "\n".join("> " + ln if ln else ">" for ln in block.split("\n"))
        self.out.append(block)

    def write(self, s):
        if self.cell is not None:
            self.cell.append(s)
        else:
            self.buf.append(s)

    # ---- parser callbacks ----
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "") or ""
        if tag == "article" and a.get("role") == "main":
            self.in_main = 1
            self.stack.append((tag, "main"))
            return
        if not self.in_main:
            return
        if tag in VOID:
            self._void(tag, a)
            return
        kind = None
        if (
            self.skip
            or tag in SKIP_TAGS
            or "headerlink" in cls
            or "toctree-wrapper" in cls
        ):
            self.skip += 1
            kind = "skip"
        self.stack.append((tag, kind))
        if self.skip:
            return
        if re.fullmatch(r"h[1-6]", tag) or tag in ("p", "dt", "dd", "li", "pre", "tr"):
            self.flush(self._li_prefix_pending() if False else "")
        if tag == "pre":
            self.pre += 1
            self.buf.append("```\n")
        elif tag == "code" and not self.pre:
            self.write("`")
        elif tag in ("em", "i") and not self.pre:
            self.write("*")
        elif tag in ("strong", "b") and not self.pre:
            self.write("**")
        elif tag == "a" and not self.pre:
            href = a.get("href")
            self.link = urljoin(self.base, href) if href else None
            self.write("[")
        elif tag in ("ul", "ol"):
            self.flush()
            self.lists.append([tag, 0])
        elif tag == "li" and self.lists:
            self.lists[-1][1] += 1
        elif tag == "div" and "admonition" in cls:
            self.flush()
            self.quote += 1
            self.stack[-1] = (tag, "quote")
        elif tag == "p" and "admonition-title" in cls:
            self.write("**")
            self.stack[-1] = (tag, "admtitle")
        elif tag == "table":
            self.flush()
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.table.append([])
        elif tag in ("td", "th") and self.table is not None:
            self.cell = []

    def _li_prefix_pending(self):
        return ""

    def _void(self, tag, a):
        if self.skip:
            return
        if tag == "br":
            self.write("\n" if self.pre else "  \n")
        elif tag == "hr":
            self.flush()
            self.emit("---")
        elif tag == "img":
            src = urljoin(self.base, a.get("src", ""))
            if "sidebar-logo" in (a.get("class") or ""):
                return
            self.write(f"![{a.get('alt', '')}]({src})")

    def handle_endtag(self, tag):
        if not self.stack:
            return
        # pop until matching tag (tolerate sloppy HTML)
        idx = len(self.stack) - 1
        while idx >= 0 and self.stack[idx][0] != tag:
            idx -= 1
        if idx < 0:
            return
        popped = self.stack[idx:]
        self.stack = self.stack[:idx]
        for t, kind in reversed(popped):
            self._close(t, kind)

    def _close(self, tag, kind):
        if kind == "main":
            self.flush()
            self.in_main = 0
            return
        if kind == "skip":
            self.skip -= 1
            return
        if self.skip or not self.in_main:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self.flush("#" * int(tag[1]) + " ")
        elif tag == "pre":
            self.pre -= 1
            code = "".join(self.buf).rstrip("\n")
            self.buf = []
            self.emit(code + "\n```")
        elif tag == "code" and not self.pre:
            self.write("`")
        elif tag in ("em", "i") and not self.pre:
            self.write("*")
        elif tag in ("strong", "b") and not self.pre:
            self.write("**")
        elif tag == "a" and not self.pre:
            self.write(f"]({self.link})" if self.link else "]")
            self.link = None
        elif kind == "admtitle":
            self.write("**")
            self.flush()
        elif tag in ("p", "dd"):
            self.flush("    " if tag == "dd" else "")
        elif tag == "dt":
            self.flush("**·** ")
        elif tag == "li" and self.lists:
            kind_, n = self.lists[-1]
            indent = "  " * (len(self.lists) - 1)
            marker = f"{n}. " if kind_ == "ol" else "- "
            self.flush(indent + marker)
        elif tag in ("ul", "ol") and self.lists:
            self.flush()
            self.lists.pop()
        elif kind == "quote":
            self.flush()
            self.quote -= 1
        elif tag in ("td", "th") and self.table is not None and self.cell is not None:
            txt = re.sub(r"\s+", " ", "".join(self.cell)).strip().replace("|", "\\|")
            if self.table:
                self.table[-1].append(txt)
            self.cell = None
        elif tag == "table" and self.table is not None:
            rows = [r for r in self.table if r]
            self.table = None
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
                lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                self.emit("\n".join(lines))
        elif tag == "div":
            self.flush()

    def handle_data(self, data):
        if not self.in_main or self.skip:
            return
        if self.pre:
            self.buf.append(data)
        else:
            self.write(data)

    def result(self):
        self.flush()
        md = "\n\n".join(self.out)
        md = re.sub(r"\n{3,}", "\n\n", md)
        return html.unescape(md).strip() + "\n"


def main():
    src, dst = sys.argv[1], sys.argv[2]
    base = sys.argv[3] if len(sys.argv) > 3 else ""
    with open(src, encoding="utf-8") as f:
        raw = f.read()
    conv = Converter(base)
    conv.feed(raw)
    md = conv.result()
    header = f"<!-- source: {base} -->\n\n" if base else ""
    with open(dst, "w", encoding="utf-8") as f:
        f.write(header + md)
    print(f"wrote {dst}: {len(md.splitlines())} lines, {len(md)} chars")


if __name__ == "__main__":
    main()
