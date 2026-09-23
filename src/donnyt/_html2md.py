"""Confluence storage format -> Markdown, using only the standard library.

Confluence stores pages as XHTML with an ``ac:``/``ri:`` namespace layered on
top for macros, placeholders and task lists. A template page carries most of its
meaning in exactly those elements -- the instruction panels and the "fill this
in" hints -- so they are translated into visible Markdown rather than dropped.

This is a pragmatic converter, not a spec-complete one: it aims to render a
template the way a human reads it on the page.
"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

_INLINE_EMPHASIS = {"strong": "**", "b": "**", "em": "_", "i": "_"}
_HEADINGS = {f"h{n}": "#" * n for n in range(1, 7)}


def _preprocess_confluence(markup: str) -> str:
    """Translate ``ac:``/``ri:`` elements into plain HTML we can then convert."""

    # Structured macros -> a visible label plus whatever rich text they wrap.
    #
    # Some macros (status, expand's title, many custom ones) carry their whole
    # meaning in <ac:parameter> attributes and have no rich-text body at all.
    # A converter that discards parameters unconditionally silently deletes
    # that content. Since we cannot know every macro a given Confluence
    # instance uses, the safe default is to keep parameter values visible
    # whenever there is no body to fall back on, rather than drop them.
    def macro(match: re.Match[str]) -> str:
        name = match.group("name")
        raw_body = match.group("body") or ""

        params = re.findall(
            r'<ac:parameter\b[^>]*ac:name="([^"]*)"[^>]*>(.*?)</ac:parameter>',
            raw_body,
            flags=re.S,
        )
        body = re.sub(r"<ac:parameter\b[^>]*>.*?</ac:parameter>", "", raw_body, flags=re.S)
        body = re.sub(r"</?ac:rich-text-body\s*>", "", body)
        body = re.sub(r"</?ac:plain-text-body\s*>", "", body)

        label = name.replace("-", " ").title()
        # "colour"/"color" params are presentation, not content -- e.g. the
        # status macro's colour swatch. Everything else (title, id, ...) is
        # kept: it is cheap to show one extra word and expensive to lose one.
        param_text = "; ".join(
            v.strip() for k, v in params if v.strip() and k.lower() not in {"colour", "color"}
        )

        tag = f"[{label}: {param_text}]" if param_text else f"[{label}]"
        return f"<p>{tag}</p>{body}" if body.strip() else f"<p>{tag}</p>"

    markup = re.sub(
        r'<ac:structured-macro\b[^>]*ac:name="(?P<name>[^"]+)"[^>]*>'
        r"(?P<body>.*?)</ac:structured-macro>",
        macro,
        markup,
        flags=re.S,
    )
    markup = re.sub(
        r'<ac:structured-macro\b[^>]*ac:name="([^"]+)"[^>]*/>',
        r"<p>[\1]</p>",
        markup,
    )

    # Template placeholders are the author's instructions -- keep them, marked.
    markup = re.sub(
        r"<ac:placeholder\b[^>]*>(.*?)</ac:placeholder>",
        r"<em>\1</em>",
        markup,
        flags=re.S,
    )

    # Task lists -> Markdown checkboxes. The status has to be read from inside
    # each task; a lookahead would see the next task's status instead.
    def task(match: re.Match[str]) -> str:
        inner = match.group(1)
        done = "<ac:task-status>complete</ac:task-status>" in inner
        return f"<li>[{'x' if done else ' '}] {inner}</li>"

    markup = re.sub(r"<ac:task\b[^>]*>(.*?)</ac:task>", task, markup, flags=re.S)
    markup = re.sub(r"<ac:task-id\b[^>]*>.*?</ac:task-id>", "", markup, flags=re.S)
    markup = re.sub(r"<ac:task-status\b[^>]*>.*?</ac:task-status>", "", markup, flags=re.S)
    markup = re.sub(r"</?ac:task-body\s*>", "", markup)
    markup = re.sub(r"<ac:task-list\b[^>]*>", "<ul>", markup)
    markup = re.sub(r"</ac:task-list\s*>", "</ul>", markup)

    # Internal page links and user mentions.
    markup = re.sub(
        r'<ac:link\b[^>]*>\s*<ri:page\b[^>]*ri:content-title="([^"]+)"[^>]*/?>.*?</ac:link>',
        r"[\1]",
        markup,
        flags=re.S,
    )
    markup = re.sub(
        r'<ac:image\b[^>]*>\s*<ri:attachment\b[^>]*ri:filename="([^"]+)"[^>]*/?>.*?</ac:image>',
        r"<p>[image: \1]</p>",
        markup,
        flags=re.S,
    )

    # Anything still namespaced is markup noise -- drop the tags, keep the text.
    markup = re.sub(r"</?(?:ac|ri):[^>]*>", "", markup)
    return markup


class _Converter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._list_stack: list[str] = []
        self._ordinals: list[int] = []
        self._in_pre = False
        self._link_href: str | None = None
        self._link_text: list[str] = []
        # Table state: rows of cells, so we can emit a Markdown table at </table>.
        self._table_rows: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._row_is_header = False
        self._header_rows = 0

    # -- output helpers ----------------------------------------------------
    def _emit(self, text: str) -> None:
        if self._cell is not None:
            self._cell.append(text)
        else:
            self.out.append(text)

    def _block_break(self) -> None:
        self._emit("\n\n")

    # -- parser hooks ------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {k: (v or "") for k, v in attrs}

        if tag in _HEADINGS:
            self._block_break()
            self._emit(_HEADINGS[tag] + " ")
        elif tag == "p":
            self._block_break()
        elif tag == "br":
            self._emit("  \n")
        elif tag == "hr":
            self._block_break()
            self._emit("---")
            self._block_break()
        elif tag in _INLINE_EMPHASIS:
            self._emit(_INLINE_EMPHASIS[tag])
        elif tag == "code" and not self._in_pre:
            self._emit("`")
        elif tag == "pre":
            self._in_pre = True
            self._block_break()
            self._emit("```\n")
        elif tag in {"ul", "ol"}:
            self._list_stack.append(tag)
            self._ordinals.append(0)
            if len(self._list_stack) == 1:
                self._block_break()
        elif tag == "li":
            depth = max(len(self._list_stack) - 1, 0)
            indent = "  " * depth
            if self._list_stack and self._list_stack[-1] == "ol":
                self._ordinals[-1] += 1
                marker = f"{self._ordinals[-1]}."
            else:
                marker = "-"
            self._emit(f"\n{indent}{marker} ")
        elif tag == "a":
            self._link_href = attributes.get("href")
            self._link_text = []
        elif tag == "table":
            self._table_rows = []
            self._header_rows = 0
        elif tag == "tr":
            self._row = []
            self._row_is_header = False
        elif tag in {"td", "th"}:
            self._cell = []
            if tag == "th":
                self._row_is_header = True
        elif tag == "img":
            alt = attributes.get("alt") or "image"
            self._emit(f"[{alt}]")

    def handle_endtag(self, tag: str) -> None:
        if tag in _HEADINGS:
            self._block_break()
        elif tag == "p":
            self._block_break()
        elif tag in _INLINE_EMPHASIS:
            self._emit(_INLINE_EMPHASIS[tag])
        elif tag == "code" and not self._in_pre:
            self._emit("`")
        elif tag == "pre":
            self._emit("\n```")
            self._in_pre = False
            self._block_break()
        elif tag in {"ul", "ol"}:
            if self._list_stack:
                self._list_stack.pop()
                self._ordinals.pop()
            if not self._list_stack:
                self._block_break()
        elif tag == "a":
            text = "".join(self._link_text).strip()
            href = self._link_href
            self._link_href = None
            self._link_text = []
            if text and href and href != text:
                self._emit(f"[{text}]({href})")
            elif text:
                self._emit(text)
        elif tag in {"td", "th"} and self._cell is not None:
            cell = " ".join("".join(self._cell).split())
            self._cell = None
            if self._row is not None:
                self._row.append(cell.replace("|", "\\|"))
        elif tag == "tr" and self._row is not None:
            if self._table_rows is not None and self._row:
                self._table_rows.append(self._row)
                if self._row_is_header and self._header_rows == 0:
                    self._header_rows = len(self._table_rows)
            self._row = None
        elif tag == "table":
            self._flush_table()

    def handle_data(self, data: str) -> None:
        if self._in_pre:
            self._emit(data)
            return

        if self._link_href is not None:
            self._link_text.append(data)
            return

        # Collapse whitespace, but keep a single separating space.
        text = re.sub(r"\s+", " ", data)
        if text.strip() or (text == " " and self.out and not self.out[-1].endswith(("\n", " "))):
            self._emit(text)

    # -- tables ------------------------------------------------------------
    def _flush_table(self) -> None:
        rows = self._table_rows or []
        self._table_rows = None
        if not rows:
            return

        width = max(len(r) for r in rows)
        padded = [r + [""] * (width - len(r)) for r in rows]

        if self._header_rows:
            header, body = padded[0], padded[1:]
        else:
            header, body = [""] * width, padded

        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(["---"] * width) + " |",
        ]
        lines += ["| " + " | ".join(r) + " |" for r in body]

        self.out.append("\n\n" + "\n".join(lines) + "\n\n")


def storage_to_markdown(storage: str) -> str:
    """Convert a Confluence storage-format body to Markdown."""
    if not storage or not storage.strip():
        return ""

    converter = _Converter()
    converter.feed(_preprocess_confluence(storage))
    converter.close()

    text = "".join(converter.out)
    text = unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline_to_storage(text: str) -> str:
    """Inline Markdown -> HTML, escaping first so user text can't inject markup."""
    out = _escape(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', out)
    return out


def markdown_to_storage(markdown: str) -> str:
    """Convert Markdown to Confluence storage format.

    Covers the subset this toolkit actually produces: headings, paragraphs,
    bullet and numbered lists, checkboxes, fenced code, rules and pipe tables.
    """
    lines = markdown.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    list_tag: str | None = None
    in_code = False
    code: list[str] = []
    table: list[list[str]] = []

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    def close_table() -> None:
        if not table:
            return
        rows = [r for r in table if not all(set(c.strip()) <= {"-", ":"} for c in r)]
        if rows:
            head, body = rows[0], rows[1:]
            cells = "".join(f"<th>{_inline_to_storage(c)}</th>" for c in head)
            html = [f"<table><tbody><tr>{cells}</tr>"]
            for row in body:
                cells = "".join(f"<td>{_inline_to_storage(c)}</td>" for c in row)
                html.append(f"<tr>{cells}</tr>")
            html.append("</tbody></table>")
            out.append("".join(html))
        table.clear()

    for line in lines:
        if line.strip().startswith("```"):
            if in_code:
                body = _escape("\n".join(code))
                out.append(f"<pre><code>{body}</code></pre>")
                code.clear()
            else:
                close_list()
                close_table()
            in_code = not in_code
            continue

        if in_code:
            code.append(line)
            continue

        stripped = line.strip()

        if stripped.startswith("|") and stripped.endswith("|"):
            close_list()
            table.append([c.strip() for c in stripped.strip("|").split("|")])
            continue
        close_table()

        if not stripped:
            close_list()
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline_to_storage(heading.group(2))}</h{level}>")
            continue

        if stripped in {"---", "***", "___"}:
            close_list()
            out.append("<hr/>")
            continue

        bullet = re.match(r"^[-*+]\s+(.*)$", stripped)
        numbered = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if bullet or numbered:
            want = "ul" if bullet else "ol"
            if list_tag != want:
                close_list()
                out.append(f"<{want}>")
                list_tag = want
            item = (bullet or numbered).group(1)
            item = re.sub(r"^\[([ xX])\]\s*", lambda m: "☑ " if m.group(1) != " " else "☐ ", item)
            out.append(f"<li>{_inline_to_storage(item)}</li>")
            continue

        close_list()
        out.append(f"<p>{_inline_to_storage(stripped)}</p>")

    if in_code and code:
        out.append(f"<pre><code>{_escape(chr(10).join(code))}</code></pre>")
    close_list()
    close_table()
    return "".join(out)
