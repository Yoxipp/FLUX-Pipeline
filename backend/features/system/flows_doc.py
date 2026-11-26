"""Build the Flows manual (resources/manual/FLUX_Flows.html) from docs/user/flows/*.md.

The Markdown files are the single source: the editor's (i) button reads
03_INDEX_NODES.md, Settings > Doc > Flows shows this HTML. The page reuses the
<style> of FLUX_Manuel.html so both manuals look the same.

Dev command (from backend/), after any change in docs/user/flows/:
    python -m features.system.flows_doc
tests/system/test_flows_doc.py fails while the HTML is out of date.

The converter only knows what docs/user/flows uses: #, ##, ### headings, paragraphs,
"* " and "1. " lists (one nested level), pipe tables, `code`, **bold**, [links];
a line starting with "<!--" is a note for the doc writers and is skipped.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BACKEND = Path(__file__).resolve().parents[2]
DOCS_DIR = BACKEND.parent / "docs" / "user" / "flows"
MANUAL_DIR = BACKEND / "resources" / "manual"
OUT = MANUAL_DIR / "FLUX_Flows.html"
TITLE = "FLUX Flows"

# (file, part id, part label, chapter id prefix)
PARTS: Tuple[Tuple[str, str, str, str], ...] = (
    ("01_GLOBAL.md", "global", "Global", "g"),
    ("02_DISPO_ET_A_VENIR.md", "dispo", "Dispo et a venir", "d"),
    ("03_INDEX_NODES.md", "nodes", "Index des nodes", "f"),
)
LINKS = {"01_GLOBAL.md": "#global", "02_DISPO_ET_A_VENIR.md": "#dispo", "03_INDEX_NODES.md": "#nodes"}
PART_LABELS = {"#global": "Global", "#dispo": "Dispo et a venir", "#nodes": "Index des nodes"}
NODE_HEADING = re.compile(r"^###\s+([a-z][a-z0-9_]*\.[a-z0-9_]+)\s*:\s*(.+)$")
LIST_ITEM = re.compile(r"^(\s*)(\*|\d+\.)\s+(.*)$")

# Same hues as the app (globals.css --fam-*), in plain values for a standalone page.
FAMILY_COLORS = {
    "event": "oklch(66% 0.085 345)", "logic": "oklch(66% 0.085 315)", "session": "oklch(66% 0.085 285)",
    "dcc": "oklch(66% 0.085 255)", "operator": "oklch(66% 0.085 225)", "flux": "oklch(66% 0.085 195)",
    "data": "oklch(66% 0.085 165)", "action": "oklch(66% 0.085 100)", "subflow": "#a3a09c", "bridge": "#8a8783",
}

EXTRA_CSS = """
/* Flows manual additions (features/system/flows_doc.py). */
.node { border:1px solid var(--line); border-left:4px solid var(--fam, var(--acc)); border-radius:8px; background:var(--soft); padding:10px 14px 4px; margin:0 0 12px; scroll-margin-top:18px; }
.node-h { display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; margin-bottom:6px; }
.node-h b { font-size:15px; color:#fff; }
.node-h code { font-size:11.5px; }
.node p.ex { border-left:3px solid var(--fam, var(--acc)); background:var(--deep); padding:6px 10px; border-radius:0 6px 6px 0; }
.tile i { font-style:normal; color:var(--mute); font-size:11.5px; }
.tile.fam { border-left-color:var(--fam); flex-direction:column; align-items:flex-start; gap:2px; }
.tile.fam span { color:var(--fam); min-width:0; }
.find { width:100%; padding:7px 10px; margin:4px 0 12px; border:1px solid var(--line); border-radius:6px; background:var(--deep); color:var(--ink); font:inherit; }
.find:focus { outline:none; border-color:var(--acc); }
.hide { display:none !important; }
"""

SCRIPT = """
(function () {
  var links = {};
  document.querySelectorAll(".side a[data-id]").forEach(function (a) { links[a.dataset.id] = a; });
  var obs = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (!e.isIntersecting || !links[e.target.id]) return;
      Object.keys(links).forEach(function (k) { links[k].classList.remove("on"); });
      links[e.target.id].classList.add("on");
    });
  }, { rootMargin: "-10% 0px -80% 0px" });
  document.querySelectorAll("section[id]").forEach(function (sec) { obs.observe(sec); });
  var find = document.getElementById("find");
  if (find) find.addEventListener("input", function () {
    var q = find.value.trim().toLowerCase();
    document.querySelectorAll("[data-find]").forEach(function (el) {
      el.classList.toggle("hide", !!q && el.dataset.find.indexOf(q) < 0);
    });
  });
})();
"""


def _inline(text: str) -> str:
    out: List[str] = []
    for part in re.split(r"(`[^`]+`)", text):
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
            continue
        s = html.escape(part, quote=False)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)

        def link(m: "re.Match[str]") -> str:
            target = LINKS.get(m.group(2))
            if not target:
                return m.group(1)
            text = PART_LABELS[target] if m.group(1).endswith(".md") else m.group(1)
            return f'<a href="{target}">{text}</a>'
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, s)
        out.append(s)
    return "".join(out)


def _table(rows: List[str]) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    body = [r for r in cells[1:] if not all(re.fullmatch(r":?-+:?", c) for c in r)]
    head = "".join(f"<th>{_inline(c)}</th>" for c in cells[0])
    lines = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in body)
    return f"<table><tr>{head}</tr>{lines}</table>"


def _list(lines: List[str]) -> str:
    # Items: (level, ordered, text); an indented line without a marker continues the item.
    items: List[List] = []
    for line in lines:
        m = LIST_ITEM.match(line)
        if m:
            items.append([1 if len(m.group(1)) >= 2 else 0, m.group(2) != "*", m.group(3)])
        elif items:
            items[-1][2] += " " + line.strip()
    out: List[str] = []
    open_tags: List[str] = []
    for level, ordered, text in items:
        while len(open_tags) > level + 1:
            out.append(f"</li></{open_tags.pop()}>")
        if len(open_tags) == level + 1:
            out.append("</li>")
        while len(open_tags) < level + 1:
            tag = "ol" if ordered else "ul"
            open_tags.append(tag)
            out.append(f"<{tag}>")
        out.append(f"<li>{_inline(text)}")
    while open_tags:
        out.append(f"</li></{open_tags.pop()}>")
    return "".join(out)


def _blocks(lines: List[str], example_class: bool = False) -> str:
    """Body Markdown (no # / ## heading) to HTML; ### becomes <h2>."""
    out: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.startswith("<!--"):     # blank, or a note for the doc writers
            i += 1
        elif line.startswith("### "):
            out.append(f"<h2>{_inline(line[4:].strip())}</h2>")
            i += 1
        elif line.startswith("|"):
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            out.append(_table(lines[i:j]))
            i = j
        elif LIST_ITEM.match(line):
            j = i + 1
            while j < len(lines) and lines[j].strip() and (LIST_ITEM.match(lines[j]) or lines[j].startswith(" ")):
                j += 1
            out.append(_list(lines[i:j]))
            i = j
        else:
            j = i + 1
            while j < len(lines) and lines[j].strip() and not lines[j].startswith(("|", "#", "<!--")) and not LIST_ITEM.match(lines[j]):
                j += 1
            text = " ".join(l.strip() for l in lines[i:j])
            cls = ' class="ex"' if example_class and text.startswith("Exemple") else ""
            out.append(f"<p{cls}>{_inline(text)}</p>")
            i = j
    return "\n".join(out)


def _split(md: str, level: int) -> Tuple[List[str], List[Tuple[str, List[str]]]]:
    """Lines before the first heading of ``level`` and (title, lines) per heading."""
    mark = "#" * level + " "
    head: List[str] = []
    parts: List[Tuple[str, List[str]]] = []
    for line in md.splitlines():
        if line.startswith(mark):
            parts.append((line[len(mark):].strip(), []))
        elif parts:
            parts[-1][1].append(line)
        else:
            head.append(line)
    return head, parts


def _number(title: str) -> Tuple[str, str]:
    m = re.match(r"^(\d+)\.\s+(.*)$", title)
    return (m.group(1), m.group(2)) if m else ("", title)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _node_card(node_type: str, label: str, lines: List[str]) -> str:
    family = node_type.split(".", 1)[0]
    find = html.escape(f"{node_type} {label}".lower())
    return (f'<div class="node" id="n-{node_type}" data-find="{find}" style="--fam:{FAMILY_COLORS.get(family, "var(--acc)")}">'
            f'<div class="node-h"><b>{html.escape(label)}</b><code>{node_type}</code></div>\n'
            f"{_blocks(lines, example_class=True)}</div>")


def _nodes_chapter(cid: str, title: str, lines: List[str]) -> Tuple[str, List[Tuple[str, str]]]:
    intro: List[str] = []
    nodes: List[Tuple[str, str, List[str]]] = []
    for line in lines:
        m = NODE_HEADING.match(line)
        if m:
            nodes.append((m.group(1), m.group(2).strip(), []))
        elif nodes:
            nodes[-1][2].append(line)
        else:
            intro.append(line)
    cards = "\n".join(_node_card(t, l, body) for t, l, body in nodes)
    return (f'<section class="chap" id="{cid}">\n<h1>{_inline(title)}</h1>\n{_blocks(intro)}\n{cards}\n</section>',
            [(t, l) for t, l, _ in nodes])


def build_html(docs_dir: Path = DOCS_DIR, manual_dir: Path = MANUAL_DIR) -> str:
    css_src = (manual_dir / "FLUX_Manuel.html").read_text(encoding="utf-8")
    css = css_src[css_src.index("<style>") + 7:css_src.index("</style>")]
    nav: List[str] = [f'<a class="brand" href="#top">FLUX <small>Flows</small></a>']
    body: List[str] = []
    families: List[Tuple[str, str, List[Tuple[str, str]]]] = []
    for number, (filename, pid, plabel, prefix) in enumerate(PARTS, start=1):
        head, chapters = _split((docs_dir / filename).read_text(encoding="utf-8"), 2)
        title = next((l[2:].strip() for l in head if l.startswith("# ")), plabel)
        intro = _blocks([l for l in head if not l.startswith("# ")])
        nav.append(f'<div class="grp">{number} · {html.escape(plabel)}</div>')
        body.append(f'<section class="part" id="{pid}">\n  <div class="n">PARTIE {number}</div>\n'
                    f'  <div class="t">{_inline(title)}</div>\n</section>')
        if pid == "nodes":
            body.append(f'<section class="chap" id="{prefix}-index">\n<h1>Tous les nodes</h1>\n{intro}\n'
                        f'<input id="find" class="find" type="search" placeholder="Chercher un node (nom ou type)">\n'
                        "@@TILES@@\n</section>")
            nav.append(f'<a href="#{prefix}-index" data-id="{prefix}-index"><span>≡</span>Tous les nodes</a>')
        elif intro:
            body.append(f'<section class="chap">\n{intro}\n</section>')
        for k, (ctitle, lines) in enumerate(chapters, start=1):
            num, name = _number(ctitle)
            if pid == "nodes":
                types = [m.group(1) for m in map(NODE_HEADING.match, lines) if m]
                cid = f"{prefix}-{types[0].split('.')[0] if types else _slug(name)}"
                section, nodes = _nodes_chapter(cid, name, lines)
                families.append((cid, name, nodes))
                nav.append(f'<a href="#{cid}" data-id="{cid}"><span>{len(nodes)}</span>{html.escape(name)}</a>')
                body.append(section)
            else:
                cid = f"{prefix}{num or k}"
                label = f"{num}. {name}" if num else name
                nav.append(f'<a href="#{cid}" data-id="{cid}"><span>{html.escape(num or str(k))}</span>{_inline(name)}</a>')
                body.append(f'<section class="chap" id="{cid}">\n<h1>{_inline(label)}</h1>\n{_blocks(lines)}\n</section>')
    tiles: List[str] = []
    for cid, name, nodes in families:
        family = cid.split("-", 1)[1]
        color = FAMILY_COLORS.get(family, "var(--acc)")
        find = html.escape(" ".join(f"{t} {l}".lower() for t, l in nodes))
        tiles.append(f'<div data-find="{find}"><h2><a href="#{cid}">{html.escape(name)}</a></h2>\n<div class="tiles">' + "".join(
            f'<a class="tile fam" style="--fam:{color}" href="#n-{t}" data-find="{html.escape((t + " " + l).lower())}">'
            f'<span>{html.escape(l)}</span><i>{t}</i></a>' for t, l in nodes) + "</div></div>")
    page = "\n\n".join(body).replace("@@TILES@@", "\n".join(tiles))
    count = sum(len(n) for _, _, n in families)
    cover = (
        '<section class="cover">\n  <div class="logo">FLUX</div>\n  <div class="sub">Flows : le graph d\'automatisation</div>\n'
        "  <p>Des petites automatisations du pipeline dessinees en nodes, comme un reseau Houdini : copier les dailies, "
        "archiver, publier, convertir, prevenir l'equipe. Partie 1 : comprendre et utiliser l'editeur. Partie 2 : ce qui "
        f"marche aujourd'hui et ce qui arrive. Partie 3 : les {count} nodes, avec un exemple chacun.</p>\n"
        '  <div class="flow">'
        '<div class="box a"><b>Button</b>depart</div><span class="arr">→</span>'
        '<div class="box"><b>FindPublishes</b>publishs du jour</div><span class="arr">→</span>'
        '<div class="box"><b>ForEach</b>un tour par publish</div><span class="arr">→</span>'
        '<div class="box"><b>Copy</b>vers les dailies</div><span class="arr">→</span>'
        '<div class="box"><b>Notify</b>previent l\'equipe</div></div>\n'
        '  <div class="go"><a class="pill-link" href="#global">1. Global</a><a class="pill-link" href="#dispo">2. Dispo et a venir</a>'
        '<a class="pill-link" href="#nodes">3. Index des nodes</a></div>\n'
        '  <div class="meta">Genere depuis <code>docs/user/flows/</code> · le bouton (i) d\'un node dans l\'editeur affiche la meme '
        "description · Licence MPL-2.0</div>\n</section>")
    return (
        '<!doctype html>\n<html lang="fr">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{TITLE}</title>\n<style>{css}{EXTRA_CSS}</style>\n</head>\n"
        '<body id="top">\n<div class="layout">\n<nav class="side">\n' + "\n".join(nav) + "\n</nav>\n<main>\n\n"
        + cover + "\n\n" + page + '\n\n</main>\n</div>\n<a class="top" href="#top">Haut</a>\n'
        f"<script>{SCRIPT}</script>\n</body>\n</html>\n")


def write(out: Optional[Path] = None) -> Path:
    out = out or OUT
    out.write_text(build_html(), encoding="utf-8", newline="\n")
    return out


if __name__ == "__main__":
    print(f"[FLUX] Flows manual written: {write()}")
