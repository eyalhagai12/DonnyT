"""Obsidian vault as a knowledge graph.

The graph is made of notes whose frontmatter ``type`` says what they are and
whose ``[[wikilinks]]`` are the edges. Obsidian's graph view then renders the
team as a picture: people connected to the sprints they worked, the merge
requests they authored, and the decisions those produced.

Two rules keep the vault genuinely usable rather than a machine dumping ground:

1. **Generated content is fenced.** Anything this toolkit writes lives between
   ``<!-- donnyt:begin <id> -->`` and ``<!-- donnyt:end <id> -->`` markers.
   Regenerating a note replaces only those blocks; prose written outside them
   is never touched.
2. **Every note is readable on its own.** Notes lead with a human summary, not
   a table of ids.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .config import Config, load_config

FM_DELIM = "---"
_BEGIN = "<!-- donnyt:begin {} -->"
_END = "<!-- donnyt:end {} -->"

# Folder per note type. These are the graph's clusters.
FOLDERS = {
    "person": "People",
    "sprint": "Sprints",
    "mr": "MRs",
    "epic": "Projects",
    "project": "Projects",
    "decision": "Decisions",
    "meeting": "Meetings",
    "topic": "Topics",
}

# The sprint brief a lead writes before planning, in Sprints/. The toolkit
# fills in the Jira facts below it once the sprint exists.
SPRINT_BRIEF_TEMPLATE = "_templates/Sprint.md"


# -- frontmatter ----------------------------------------------------------
# A deliberately small YAML subset: scalars and flat lists, which is all
# Obsidian frontmatter needs and all this toolkit writes. Avoids a PyYAML
# dependency that would have to be vendored for offline install.


def _scalar(value: str) -> Any:
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [_scalar(p) for p in _split_list(inner)] if inner else []
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text in {"true", "True"}:
        return True
    if text in {"false", "False"}:
        return False
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


def _split_list(inner: str) -> list[str]:
    """Split a flow list on commas that are not inside quotes or wikilinks."""
    parts, buf, quote, depth = [], [], "", 0
    for char in inner:
        if quote:
            if char == quote:
                quote = ""
            buf.append(char)
        elif char in "\"'":
            quote = char
            buf.append(char)
        elif char == "[":
            depth += 1
            buf.append(char)
        elif char == "]":
            depth -= 1
            buf.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(char)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a note into (frontmatter, body)."""
    if not text.startswith(FM_DELIM):
        return {}, text

    lines = text.split("\n")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == FM_DELIM), None)
    if end is None:
        return {}, text

    data: dict[str, Any] = {}
    key: str | None = None
    for line in lines[1:end]:
        if not line.strip() or line.strip().startswith("#"):
            continue
        item = re.match(r"^\s+-\s+(.*)$", line)
        if item and key:
            data.setdefault(key, [])
            if isinstance(data[key], list):
                data[key].append(_scalar(item.group(1)))
            continue
        name, sep, value = line.partition(":")
        if not sep:
            continue
        key = name.strip()
        data[key] = [] if not value.strip() else _scalar(value)

    return data, "\n".join(lines[end + 1 :]).lstrip("\n")


def dump_frontmatter(data: dict[str, Any]) -> str:
    lines = [FM_DELIM]
    for key, value in data.items():
        if value is None or value == "":
            continue
        if isinstance(value, list):
            if not value:
                continue
            lines.append(f"{key}:")
            lines.extend(f"  - {_emit(v)}" for v in value)
        elif isinstance(value, bool):
            lines.append(f"{key}: {str(value).lower()}")
        else:
            lines.append(f"{key}: {_emit(value)}")
    lines.append(FM_DELIM)
    return "\n".join(lines)


def _emit(value: Any) -> str:
    if isinstance(value, (int, float, bool)):
        return str(value)
    text = str(value)
    # Quote anything YAML would misread -- a leading [[ is the common case.
    if text.startswith(("[", "{", "*", "&", "!", "|", ">", "%", "@")) or ": " in text or text.endswith(":"):
        return '"{}"'.format(text.replace('"', '\\"'))
    return text


# -- naming ---------------------------------------------------------------

_UNSAFE = r'[<>:"/\\|?*\x00-\x1f]'


def slug(title: str) -> str:
    """A filename-safe note title that still reads as the thing it names."""
    cleaned = re.sub(_UNSAFE, "-", title).strip(" .-")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120] or "untitled"


def link(title: str, alias: str | None = None) -> str:
    target = slug(title)
    return f"[[{target}|{alias}]]" if alias and alias != target else f"[[{target}]]"


def links(titles: list[str]) -> list[str]:
    return [link(t) for t in titles if t]


def unlink(text: str) -> str:
    """``[[Target|alias]]`` -> ``Target``: the note a cell or bullet names."""
    return re.sub(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]", lambda m: m.group(1).strip(), text).strip()


# -- reading hand-written notes -------------------------------------------
# Briefs and person notes are written by people, in Obsidian. These read the
# few shapes they use -- ## sections, bullet lists, tables -- and tolerate
# everything else by returning it as text.

_HEADING = re.compile(r"^(#{1,2})\s+(.+?)\s*#*\s*$")


def sections(body: str) -> dict[str, str]:
    """Every ``## heading`` in a note, mapped to the text under it.

    Managed blocks are left out: they hold generated content, not what the
    author wrote. So are comments -- ``%% … %%`` (Obsidian's, hidden when
    reading) and ``<!-- … -->`` -- which is where templates put guidance.
    """
    text = re.sub(r"<!-- donnyt:begin (\S+) -->.*?<!-- donnyt:end \1 -->", "", body, flags=re.S)
    text = re.sub(r"%%.*?%%|<!--.*?-->", "", text, flags=re.S)
    found: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in text.split("\n"):
        match = _HEADING.match(line)
        if match:
            if current is not None:
                found[current] = "\n".join(lines).strip()
            current = match.group(2) if len(match.group(1)) == 2 else None
            lines = []
        elif current is not None:
            lines.append(line)
    if current is not None:
        found[current] = "\n".join(lines).strip()
    return found


def section(body: str, heading: str) -> str:
    """The text under ``## heading`` (case-insensitive), or ``""``."""
    wanted = heading.strip().lower()
    return next((text for name, text in sections(body).items() if name.lower() == wanted), "")


def bullets(text: str) -> list[str]:
    """Non-empty ``-``/``*`` list items. A lone ``-`` placeholder is skipped."""
    items = (re.match(r"^\s*[-*+]\s+(.*)$", line) for line in text.split("\n"))
    return [m.group(1).strip() for m in items if m and m.group(1).strip()]


def _cells(row: str) -> list[str]:
    """Split a table row on ``|``, except inside ``[[a|b]]`` or when escaped."""
    text = row.strip()
    text = text[1:] if text.startswith("|") else text
    text = text[:-1] if text.endswith("|") and not text.endswith("\\|") else text
    cells: list[str] = []
    buf: list[str] = []
    depth = i = 0
    while i < len(text):
        pair = text[i : i + 2]
        if pair == "[[" or (pair == "]]" and depth):
            depth += 1 if pair == "[[" else -1
            buf.append(pair)
            i += 2
        elif pair == "\\|":  # Obsidian escapes the alias pipe inside tables
            buf.append("|")
            i += 2
        elif text[i] == "|" and not depth:
            cells.append("".join(buf).strip())
            buf = []
            i += 1
        else:
            buf.append(text[i])
            i += 1
    cells.append("".join(buf).strip())
    return cells


def parse_table(text: str) -> list[dict[str, str]]:
    """The first Markdown table in ``text``, as rows keyed by header.

    Wikilinks are unwrapped to the note they name. Rows with nothing in them
    but placeholders (``—``, ``-``) are dropped, so an unfilled template row
    is not a person.
    """
    rows = [line for line in text.split("\n") if line.strip().startswith("|")]
    if len(rows) < 2:
        return []
    header = [unlink(c) for c in _cells(rows[0])]
    body = rows[2:] if re.fullmatch(r"[\s|:\-]+", rows[1]) else rows[1:]
    table = []
    for row in body:
        values = [unlink(c) for c in _cells(row)]
        if all(v in ("", "-", "—", "–") for v in values):
            continue
        table.append({h: (values[i] if i < len(values) else "") for i, h in enumerate(header)})
    return table


# -- the vault ------------------------------------------------------------


def _is_graph_note(path: Path, root: Path) -> bool:
    """True for real notes. Templates, READMEs and dot-folders are not graph nodes."""
    if path.suffix != ".md" or path.name == "README.md":
        return False
    return not any(
        part.startswith(".") or part.startswith("_")
        for part in path.relative_to(root).parts
    )


@dataclass
class Note:
    path: Path
    frontmatter: dict[str, Any]
    body: str

    @property
    def title(self) -> str:
        return self.path.stem


class Vault:
    def __init__(self, path: Path | str | None = None, config: Config | None = None) -> None:
        if path is not None:
            self.path = Path(path)
        else:
            self.config = config or load_config()
            self.path = self.config.vault_path
        self.path.mkdir(parents=True, exist_ok=True)

    # -- paths -------------------------------------------------------------
    def note_path(self, title: str, kind: str = "topic") -> Path:
        folder = FOLDERS.get(kind, "Topics")
        return self.path / folder / f"{slug(title)}.md"

    def resolve(self, title: str) -> Path | None:
        """Find an existing note by title anywhere in the vault."""
        target = f"{slug(title)}.md"
        return next(
            (p for p in self.path.rglob("*.md")
             if p.name == target and _is_graph_note(p, self.path)),
            None,
        )

    # -- read / write ------------------------------------------------------
    def read(self, title_or_path: str | Path) -> Note | None:
        path = (
            Path(title_or_path)
            if isinstance(title_or_path, Path)
            else self.resolve(str(title_or_path))
        )
        if path is None or not path.exists():
            return None
        frontmatter, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        return Note(path=path, frontmatter=frontmatter, body=body)

    def write(self, path: Path, frontmatter: dict[str, Any], body: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{dump_frontmatter(frontmatter)}\n\n{body.strip()}\n", encoding="utf-8")
        return path

    def upsert(
        self,
        title: str,
        kind: str,
        frontmatter: dict[str, Any],
        blocks: dict[str, str],
        intro: str = "",
    ) -> Path:
        """Create or refresh a note, preserving anything hand-written.

        ``blocks`` maps a stable block id to generated Markdown. Existing blocks
        with the same id are replaced in place; new ones are appended. Prose
        outside the markers survives untouched, and so does any frontmatter key
        this call does not set.
        """
        path = self.note_path(title, kind)
        existing = self.read(path)

        if existing:
            merged = {**existing.frontmatter, **frontmatter}
            body = existing.body
        else:
            merged = {"type": kind, "created": date.today().isoformat(), **frontmatter}
            body = f"# {title}\n\n{intro}".rstrip() + "\n"

        merged["updated"] = date.today().isoformat()

        for block_id, content in blocks.items():
            body = _replace_block(body, block_id, content)

        return self.write(path, merged, body)

    # -- graph queries -----------------------------------------------------
    def notes(self, kind: str | None = None) -> list[Note]:
        found = []
        for path in sorted(self.path.rglob("*.md")):
            if not _is_graph_note(path, self.path):
                continue
            note = self.read(path)
            if note and (kind is None or note.frontmatter.get("type") == kind):
                found.append(note)
        return found

    def backlinks(self, title: str) -> list[str]:
        """Note titles that link to ``title`` -- the inbound edges."""
        target = slug(title)
        pattern = re.compile(r"\[\[" + re.escape(target) + r"(\||\]\])")
        return sorted(
            path.stem
            for path in self.path.rglob("*.md")
            if _is_graph_note(path, self.path)
            and path.stem != target
            and pattern.search(path.read_text(encoding="utf-8", errors="replace"))
        )

    def outlinks(self, title: str) -> list[str]:
        note = self.read(title)
        if not note:
            return []
        raw = f"{dump_frontmatter(note.frontmatter)}\n{note.body}"
        return sorted({m.group(1).strip() for m in re.finditer(r"\[\[([^\]|#]+)", raw)})

    def search(self, query: str, limit: int = 30) -> list[dict[str, Any]]:
        """Case-insensitive full-text search with one line of context per hit."""
        needle = query.lower()
        hits: list[dict[str, Any]] = []
        for path in sorted(self.path.rglob("*.md")):
            if not _is_graph_note(path, self.path):
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                if needle in line.lower():
                    hits.append(
                        {
                            "note": path.stem,
                            "path": str(path.relative_to(self.path)),
                            "line": number,
                            "text": line.strip()[:200],
                        }
                    )
                    if len(hits) >= limit:
                        return hits
        return hits

    def stats(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for note in self.notes():
            kind = str(note.frontmatter.get("type", "untyped"))
            counts[kind] = counts.get(kind, 0) + 1
        return {"path": str(self.path), "total_notes": sum(counts.values()), "by_type": counts}


def _replace_block(body: str, block_id: str, content: str) -> str:
    begin, end = _BEGIN.format(block_id), _END.format(block_id)
    fenced = f"{begin}\n{content.strip()}\n{end}"

    pattern = re.compile(
        re.escape(begin) + r".*?" + re.escape(end),
        re.S,
    )
    if pattern.search(body):
        return pattern.sub(lambda _: fenced, body, count=1)
    return body.rstrip() + f"\n\n{fenced}\n"
