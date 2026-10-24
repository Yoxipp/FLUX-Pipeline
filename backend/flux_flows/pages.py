# pages.py — the TOOL page YAML schema and its validation (04_PAGES_TOOL §2, §3, §8, ADR 0066).
#
# A page is the interface of one or more flows: a grid (folder > row > widget, 0057
# n°13). Form widgets SEND values to a flow; data widgets SHOW records of a source
# (a data collection of the page, the last run of a flow, or a builtin source) and
# the board widget holds a free surface inside its own row (ADR 0066).
#
# Same rules as model.py for flows:
#   * strict pydantic schema (``extra="forbid"``) + per kind props: a typo fails with
#     the field path;
#   * the model checks the SHAPE; ids, links to flows, sources and types are reported
#     by ``validate_page`` (codes P_*) so a page the editor saved always reloads;
#   * ``scope`` is written by the store for humans and ignored on read;
#   * our own emitter, one widget per line, stable key order.

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Literal, Optional, Tuple

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from flux_flows.model import FIELD_ID_RE, NAME_RE, Flow, _flow_style, _scalar

PAGE_FORMAT = 1
MAX_BYTES = 512 * 1024
MAX_WIDGETS = 300
MAX_ROW = 4
LABEL_MAX = 80
MAX_DEPTH = 4                      # folders inside folders
SCOPES = ("team", "project")       # no perso page (A16)
PAGE_SCOPES = SCOPES + ("shipped",)

# Kind -> its own props (04 §3, ADR 0066). Common props are in COMMON_PROPS.
FORM_KINDS = ("button", "float", "int", "text", "path", "dir", "toggle", "select", "list")
DECOR_KINDS = ("separator", "label")
DATA_KINDS = ("feed", "table", "cards", "calendar", "members", "board")
KINDS = FORM_KINDS + DECOR_KINDS + DATA_KINDS
VALUE_KINDS = tuple(k for k in FORM_KINDS if k != "button")
KIND_PROPS: Dict[str, Tuple[str, ...]] = {
    "button": ("icon", "confirm", "on_click"),
    "float": ("min", "max", "step", "unit"),
    "int": ("min", "max", "step"),
    "text": ("multiline", "placeholder", "max_len"),
    "path": ("mode", "filters"),
    "dir": (),
    "toggle": (),
    "select": ("options",),
    "list": ("item",),
    "separator": (),
    "label": ("text",),
    "feed": ("source", "field", "group_by", "height"),
    "table": ("source", "columns", "editable"),
    "cards": ("source", "title", "group_by", "editable"),
    "calendar": ("source", "date", "end", "title"),
    "members": ("source",),
    "board": ("source", "height"),
}
COMMON_PROPS = ("id", "kind", "label", "tooltip", "w")
VALUE_PROPS = ("default", "remember", "bind")

# Value type a form widget sends, and the interface types it may feed (04 §3, B3:
# identity or a safe conversion: int -> float, path -> str, dir -> path).
FEEDS: Dict[str, Tuple[str, ...]] = {
    "float": ("float",),
    "int": ("int", "float"),
    "text": ("str", "pattern"),
    "path": ("path", "str"),
    "dir": ("dir", "path", "str"),
    "toggle": ("bool",),
    "select": ("select", "str"),
    "list": ("list[str]",),
}
# Interface type -> the widget kind a generated form uses (04 §7).
KIND_FOR_TYPE = {"float": "float", "int": "int", "bool": "toggle", "str": "text", "pattern": "text",
                 "path": "path", "dir": "dir", "select": "select", "list[str]": "list"}

# Data collections (ADR 0066 n°3).
FIELD_TYPES = ("str", "text", "int", "float", "bool", "date", "datetime", "user", "select", "image", "path")
DATE_TYPES = ("date", "datetime")
BOARD_FIELDS = ("type", "x", "y", "w", "h", "text", "color", "image", "from", "to")
BUILTIN_SOURCES = ("users",)
DATA_SOURCE_KINDS = {"feed": "records", "table": "records", "cards": "records", "calendar": "records",
                     "board": "board"}

# Static routes of /flows/pages: a page cannot take one of these ids.
RESERVED_IDS = frozenset("validate links templates data media".split())
PAGE_ICONS = frozenset(
    "wrench film camera clapperboard folder box package layers image brush palette calendar "
    "message-square users kanban layout-dashboard list-checks rocket send bell star zap".split()
)


class PageSchemaError(ValueError):
    """The text or document is not a valid page. The message names the field."""


# -- schema -------------------------------------------------------------------

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Option(_Strict):
    value: str
    label: str = ""


class Bind(_Strict):
    flow: str
    param: str


class OnClick(_Strict):
    flow: str
    button_id: str


class Source(_Strict):
    data: Optional[str] = None                 # a collection of this page
    flow: Optional[str] = None                 # the last run of a flow ...
    output: Optional[str] = None               # ... and one of its interface outputs
    builtin: Optional[Literal["users"]] = None

    @model_validator(mode="after")
    def _one(self) -> "Source":
        given = [k for k in ("data", "flow", "builtin") if getattr(self, k) is not None]
        if len(given) != 1:
            raise ValueError("une source est data, flow (+ output) ou builtin, une seule")
        if (self.output is not None) != (self.flow is not None):
            raise ValueError("'output' va avec 'flow'")
        return self


class Widget(_Strict):
    id: str
    kind: str
    label: str = ""
    tooltip: str = ""
    w: Optional[float] = None
    default: Any = None
    remember: Optional[Literal["user", "none"]] = None
    bind: Optional[Bind] = None
    # button
    icon: Optional[str] = None
    confirm: Optional[str] = None
    on_click: Optional[OnClick] = None
    # numbers
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    unit: Optional[str] = None
    # text
    multiline: Optional[bool] = None
    placeholder: Optional[str] = None
    max_len: Optional[int] = None
    # path
    mode: Optional[Literal["open", "save"]] = None
    filters: Optional[List[str]] = None
    # select / list / label
    options: Optional[List[Option]] = None
    item: Optional[Literal["str"]] = None
    text: Optional[str] = None
    # data widgets
    source: Optional[Source] = None
    field: Optional[str] = None
    group_by: Optional[str] = None
    columns: Optional[List[str]] = None
    editable: Optional[bool] = None
    title: Optional[str] = None
    date: Optional[str] = None
    end: Optional[str] = None
    height: Optional[int] = None

    @model_validator(mode="after")
    def _props(self) -> "Widget":
        if self.kind not in KINDS:
            raise ValueError(f"kind '{self.kind}' inconnu (attendu : {', '.join(KINDS)})")
        allowed = set(COMMON_PROPS) | set(KIND_PROPS[self.kind])
        if self.kind in VALUE_KINDS:
            allowed |= set(VALUE_PROPS)
        extra = [k for k in self.model_fields_set if k not in allowed and getattr(self, k) is not None]
        if extra:
            raise ValueError(f"{self.kind} '{self.id}' : propriete(s) {', '.join(sorted(extra))} non prise(s) en charge")
        if self.kind == "members" and self.source is None:
            self.source = Source(builtin="users")
        if self.w is not None and not 0 < self.w <= 12:
            raise ValueError("w : poids entre 0 et 12")
        if self.height is not None and not 120 <= self.height <= 4000:
            raise ValueError("height : entre 120 et 4000 px")
        return self


class Folder(_Strict):
    id: str
    label: str = ""
    mode: Literal["plain", "tabs", "collapsible"] = "plain"


class LayoutItem(_Strict):
    folder: Optional[Folder] = None
    children: Optional[List["LayoutItem"]] = None
    row: Optional[List[Widget]] = None

    @model_validator(mode="after")
    def _one(self) -> "LayoutItem":
        if (self.folder is None) == (self.row is None):
            raise ValueError("un element de layout est un folder (+ children) ou une row")
        if self.row is not None and self.children is not None:
            raise ValueError("'children' va avec 'folder'")
        if self.folder is not None and self.children is None:
            self.children = []
        if self.row is not None and not self.row:
            raise ValueError("une row vide")
        return self


class DataField(_Strict):
    id: str
    type: str
    label: str = ""
    options: Optional[List[Option]] = None
    required: bool = False

    @model_validator(mode="after")
    def _check(self) -> "DataField":
        if self.type not in FIELD_TYPES:
            raise ValueError(f"champ '{self.id}' : type '{self.type}' inconnu (attendu : {', '.join(FIELD_TYPES)})")
        if (self.options is not None) != (self.type == "select"):
            raise ValueError(f"champ '{self.id}' : 'options' va avec le type select, et seulement lui")
        return self


class DataSpec(_Strict):
    id: str
    label: str = ""
    kind: Literal["records", "board"] = "records"
    per: Literal["project", "team"] = "project"       # where the records live (ADR 0066 n°3)
    write: Literal["all", "team_td"] = "all"          # who may add / change records
    fields: List[DataField] = []

    @model_validator(mode="after")
    def _check(self) -> "DataSpec":
        if self.kind == "board" and self.fields:
            raise ValueError(f"donnees '{self.id}' : un board a ses champs fixes ({', '.join(BOARD_FIELDS)})")
        return self


class Page(_Strict):
    page: int
    id: str
    label: str = ""
    icon: str = "wrench"
    scope: Optional[str] = None       # written by the store, ignored on read
    description: str = ""
    data: List[DataSpec] = []
    layout: List[LayoutItem] = []

    @model_validator(mode="after")
    def _check(self) -> "Page":
        if self.page != PAGE_FORMAT:
            raise ValueError(f"format de page {self.page} non pris en charge (attendu {PAGE_FORMAT})")
        if not NAME_RE.match(self.id):
            raise ValueError("id de page invalide : minuscules, chiffres et _, 2 a 41 caracteres, commence par une lettre")
        if self.id in RESERVED_IDS:
            raise ValueError(f"l'id de page '{self.id}' est reserve")
        if len(self.label) > LABEL_MAX:
            raise ValueError(f"libelle trop long (max {LABEL_MAX} caracteres)")
        if self.icon not in PAGE_ICONS:
            raise ValueError(f"icone '{self.icon}' hors liste (attendu : {', '.join(sorted(PAGE_ICONS))})")
        depth = max((d for d, _ in _walk_folders(self.layout)), default=0)
        if depth > MAX_DEPTH:
            raise ValueError(f"{depth} niveaux de dossiers : maximum {MAX_DEPTH}")
        count = sum(1 for _ in iter_widgets(self))
        if count > MAX_WIDGETS:
            raise ValueError(f"{count} widgets : maximum {MAX_WIDGETS}")
        return self


LayoutItem.model_rebuild()


def _walk_folders(items: List[LayoutItem], depth: int = 0) -> Iterator[Tuple[int, Folder]]:
    for item in items:
        if item.folder is not None:
            yield depth + 1, item.folder
            yield from _walk_folders(item.children or [], depth + 1)


def _rows(items: List[LayoutItem]) -> Iterator[List[Widget]]:
    for item in items:
        if item.row is not None:
            yield item.row
        else:
            yield from _rows(item.children or [])


def iter_widgets(page: Page) -> Iterator[Widget]:
    """Every widget, in layout order."""
    for row in _rows(page.layout):
        yield from row


def folders(page: Page) -> List[Folder]:
    return [f for _, f in _walk_folders(page.layout)]


# -- read ---------------------------------------------------------------------

def _format_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err.get("loc", ())) or "page"
        msg = str(err.get("msg", "")).removeprefix("Value error, ")
        parts.append(f"{where} : {msg}")
    return " ; ".join(parts)


def parse_page(data: Any) -> Page:
    """Validate a decoded page document. ``scope`` is dropped."""
    if not isinstance(data, dict):
        raise PageSchemaError("une page est un document YAML de type map")
    try:
        page = Page.model_validate(data)
    except ValidationError as exc:
        raise PageSchemaError(_format_error(exc)) from None
    page.scope = None
    return page


def load_page_text(text: str) -> Page:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise PageSchemaError(f"fichier trop gros (max {MAX_BYTES // 1024} Ko)")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PageSchemaError(f"YAML illisible : {exc}") from None
    return parse_page(data)


# -- emit ---------------------------------------------------------------------

_WIDGET_ORDER = COMMON_PROPS + VALUE_PROPS + tuple(dict.fromkeys(p for props in KIND_PROPS.values() for p in props))


def _clean(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return {k: _clean(v) for k, v in value.model_dump(exclude_none=True).items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def widget_doc(widget: Widget) -> Dict[str, Any]:
    doc: Dict[str, Any] = {}
    for key in _WIDGET_ORDER:
        value = getattr(widget, key)
        if value is None or (key in ("label", "tooltip") and value == ""):
            continue
        if key == "source" and widget.kind == "members" and value == Source(builtin="users"):
            continue
        doc[key] = _clean(value)
    return doc


def _data_doc(spec: DataSpec) -> Dict[str, Any]:
    doc: Dict[str, Any] = {"id": spec.id}
    if spec.label:
        doc["label"] = spec.label
    for key, default in (("kind", "records"), ("per", "project"), ("write", "all")):
        if getattr(spec, key) != default:
            doc[key] = getattr(spec, key)
    if spec.fields:
        doc["fields"] = [{k: v for k, v in _clean(f).items() if not (k == "required" and v is False)
                          and not (k == "label" and v == "")} for f in spec.fields]
    return doc


def _emit_layout(out: List[str], items: List[LayoutItem], indent: int) -> None:
    pad = " " * indent
    for item in items:
        if item.folder is not None:
            out.append(f"{pad}- folder: {_flow_style(_clean(item.folder))}")
            out.append(f"{pad}  children:" + ("" if item.children else " []"))
            _emit_layout(out, item.children or [], indent + 4)
        else:
            out.append(f"{pad}- row:")
            out += [f"{pad}    - {_flow_style(widget_doc(w))}" for w in item.row or []]


def dump_page(page: Page, *, scope: Optional[str] = None) -> str:
    """Stable YAML text. Without ``scope`` it is the canonical content (rev)."""
    out = [f"page: {PAGE_FORMAT}", f"id: {page.id}"]
    if page.label:
        out.append(f"label: {_scalar(page.label)}")
    out.append(f"icon: {_scalar(page.icon)}")
    if scope is not None:
        out.append(f"scope: {scope}")
    if page.description:
        out.append(f"description: {_scalar(page.description)}")
    out.append("data:" + ("" if page.data else " []"))
    out += [f"  - {_flow_style(_data_doc(d))}" for d in page.data]
    out.append("layout:" + ("" if page.layout else " []"))
    _emit_layout(out, page.layout, 2)
    return "\n".join(out) + "\n"


def to_document(page: Page) -> Dict[str, Any]:
    """JSON document for the front (same keys as the YAML)."""
    return yaml.safe_load(dump_page(page))


# -- ids ----------------------------------------------------------------------

_ACCENTS = str.maketrans("àâäáãéèêëíìîïóòôöõúùûüçñÀÂÄÁÃÉÈÊËÍÌÎÏÓÒÔÖÕÚÙÛÜÇÑ",
                         "aaaaaeeeeiiiiooooouuuucnAAAAAEEEEIIIIOOOOOUUUUCN")


def suggest_id(label: str, taken: Optional[set] = None) -> str:
    """Readable id from a label (04 §4): "Dossier de destination" -> dossier_de_destination."""
    text = re.sub(r"[^a-z0-9]+", "_", (label or "").translate(_ACCENTS).lower()).strip("_")
    if not text or not text[0].isalpha():
        text = f"w_{text}" if text else "widget"
    base = text[:41].rstrip("_")
    taken = taken or set()
    candidate, n = base, 2
    while candidate in taken:
        suffix = f"_{n}"
        candidate, n = base[:41 - len(suffix)] + suffix, n + 1
    return candidate


# -- validation (04 §8) -------------------------------------------------------

ERROR, WARNING = "error", "warning"

_WHY = {
    "P_ID_INVALID": ("les liens passent par les ids", "links go through ids"),
    "P_ID_DUPLICATE": ("un id designe un seul widget", "an id names one widget"),
    "P_BUTTON_NO_FLOW": ("le bouton ne fait rien", "the button does nothing"),
    "P_FLOW_NOT_FOUND": ("rien a lancer", "nothing to run"),
    "P_BUTTON_MISSING_IN_FLOW": ("le flow ne reagit pas a ce bouton", "the flow does not react to this button"),
    "P_BUTTON_ORPHAN": ("le flow ne se lance que depuis l'editeur", "the flow only starts from the editor"),
    "P_PARAM_NOT_FOUND": ("la valeur n'arriverait nulle part", "the value would go nowhere"),
    "P_TYPE_MISMATCH": ("pas de conversion sourde", "no silent conversion"),
    "P_REQUIRED_UNBOUND": ("le flow echouerait", "the flow would fail"),
    "P_PARAM_UNBOUND": ("la valeur par defaut sera utilisee", "the default value will be used"),
    "P_FLOW_INACTIVE": ("un bouton ne lance qu'un flow actif (A7)", "a button only runs an active flow (A7)"),
    "P_FLOW_INVALID": ("le moteur refuserait le run", "the engine would refuse the run"),
    "P_SCOPE_MISMATCH": ("les autres postes ne voient pas ce flow", "other computers do not see this flow"),
    "P_OPTIONS_EMPTY": ("rien a choisir", "nothing to choose"),
    "P_ROW_TOO_WIDE": ("grille de 4 colonnes", "4 column grid"),
    "P_NO_BUTTON": ("les champs ne declenchent rien", "the fields trigger nothing"),
    "P_PUBLISH_NO_EVENT": ("le panneau ne peut rien lancer", "the panel cannot run anything"),
    "P_SOURCE_MISSING": ("le widget n'a rien a montrer", "the widget has nothing to show"),
    "P_SOURCE_NOT_FOUND": ("le widget n'a rien a montrer", "the widget has nothing to show"),
    "P_SOURCE_KIND": ("le widget ne sait pas lire ces donnees", "the widget cannot read this data"),
    "P_FIELD_NOT_FOUND": ("le widget lirait un champ vide", "the widget would read an empty field"),
    "P_FIELD_TYPE": ("le widget ne sait pas lire ce champ", "the widget cannot read this field"),
    "P_FIELDS_EMPTY": ("une collection sans champ ne garde rien", "a collection without fields keeps nothing"),
    "P_BOARD_ROW": ("le board prend toute la largeur", "the board takes the full width"),
    "P_OUTPUT_NOT_FOUND": ("le widget n'a rien a montrer", "the widget has nothing to show"),
    "P_DATA_UNUSED": ("collection sans widget", "collection without a widget"),
}


@dataclass
class PageIssue:
    level: str
    code: str
    widget: Optional[str]
    message_fr: str
    message_en: str
    why_fr: str = ""
    why_en: str = ""
    fix: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"level": self.level, "code": self.code, "widget": self.widget, "message_fr": self.message_fr,
                "message_en": self.message_en, "why_fr": self.why_fr, "why_en": self.why_en, "fix": self.fix}


def _issue(code: str, widget: Optional[str], fr: str, en: str, fix: Optional[Dict[str, Any]] = None) -> PageIssue:
    level = WARNING if code in ("P_BUTTON_ORPHAN", "P_PARAM_UNBOUND", "P_FLOW_INACTIVE", "P_NO_BUTTON",
                                "P_DATA_UNUSED") else ERROR
    why_fr, why_en = _WHY[code]
    return PageIssue(level, code, widget, fr, en, why_fr, why_en, fix)


@dataclass
class FlowInfo:
    """What a page needs to know about a flow it is linked to."""
    scope: str
    flow: Flow
    active: bool = False
    valid: Optional[bool] = None


@dataclass
class PageEnv:
    scope: Optional[str] = None                                  # scope of the page
    flow_lookup: Optional[Callable[[str], Optional[FlowInfo]]] = None


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _closest(name: str, choices: List[str]) -> Optional[str]:
    best = min(choices, key=lambda c: _edit_distance(name, c), default=None)
    return best if best is not None and _edit_distance(name, best) <= 3 else None


def _check_ids(page: Page, issues: List[PageIssue]) -> None:
    seen: set = set()
    named = [("widget", w.id) for w in iter_widgets(page)] + [("folder", f.id) for f in folders(page)]
    for what, wid in named:
        if not FIELD_ID_RE.match(wid or ""):
            fixed = suggest_id(wid, seen)
            issues.append(_issue("P_ID_INVALID", wid,
                                 f"`{wid}` n'est pas un id valide : minuscules, chiffres et _ (ex. {fixed}).",
                                 f"`{wid}` is not a valid id: lowercase, digits and _ (e.g. {fixed}).",
                                 {"kind": "rename", "args": {"id": wid, "to": fixed}}))
        elif wid in seen:
            fixed = suggest_id(wid, seen)
            issues.append(_issue("P_ID_DUPLICATE", wid,
                                 f"L'id `{wid}` existe deja dans cette page : renomme l'un des deux.",
                                 f"The id `{wid}` already exists in this page: rename one of them.",
                                 {"kind": "rename", "args": {"id": wid, "to": fixed}}))
        seen.add(wid)
    data_seen: set = set()
    for spec in page.data:
        if not FIELD_ID_RE.match(spec.id):
            issues.append(_issue("P_ID_INVALID", None, f"Collection : `{spec.id}` n'est pas un id valide.",
                                 f"Collection: `{spec.id}` is not a valid id."))
        elif spec.id in data_seen:
            issues.append(_issue("P_ID_DUPLICATE", None, f"La collection `{spec.id}` existe deux fois.",
                                 f"The collection `{spec.id}` exists twice."))
        data_seen.add(spec.id)
        field_ids = [f.id for f in spec.fields]
        bad = [f for f in field_ids if not FIELD_ID_RE.match(f) or field_ids.count(f) > 1]
        if bad:
            issues.append(_issue("P_ID_INVALID", None,
                                 f"Collection `{spec.id}` : champ(s) {', '.join(sorted(set(bad)))} invalide(s) ou en double.",
                                 f"Collection `{spec.id}`: field(s) {', '.join(sorted(set(bad)))} invalid or duplicated."))
        if spec.kind == "records" and not spec.fields:
            issues.append(_issue("P_FIELDS_EMPTY", None, f"La collection `{spec.id}` n'a aucun champ.",
                                 f"The collection `{spec.id}` has no field.", {"kind": "add_field", "args": {"data": spec.id}}))
        for f in spec.fields:
            if f.type == "select" and not f.options:
                issues.append(_issue("P_OPTIONS_EMPTY", None, f"Le champ `{spec.id}.{f.id}` n'a aucune option.",
                                     f"The field `{spec.id}.{f.id}` has no option."))


def _check_rows(page: Page, issues: List[PageIssue]) -> None:
    for row in _rows(page.layout):
        if len(row) > MAX_ROW:
            issues.append(_issue("P_ROW_TOO_WIDE", row[0].id,
                                 f"Une ligne a {len(row)} widgets : {MAX_ROW} colonnes au maximum.",
                                 f"A row has {len(row)} widgets: {MAX_ROW} columns at most.",
                                 {"kind": "split_row", "args": {"widget": row[0].id}}))
        if len(row) > 1:
            for w in row:
                if w.kind == "board":
                    issues.append(_issue("P_BOARD_ROW", w.id, f"Le board `{w.id}` doit etre seul sur sa ligne.",
                                         f"The board `{w.id}` must be alone in its row.",
                                         {"kind": "split_row", "args": {"widget": w.id}}))


def _flow(env: PageEnv, name: str) -> Optional[FlowInfo]:
    return env.flow_lookup(name) if env.flow_lookup else None


def _check_flow_ref(env: PageEnv, wid: str, name: str, issues: List[PageIssue]) -> Optional[FlowInfo]:
    info = _flow(env, name)
    if env.flow_lookup is None:
        return None
    if info is None:
        issues.append(_issue("P_FLOW_NOT_FOUND", wid,
                             f"Le flow `{name}` n'existe plus : choisis un autre flow ou restaure une version.",
                             f"The flow `{name}` no longer exists: pick another flow or restore a version.",
                             {"kind": "pick_flow", "args": {"widget": wid}}))
        return None
    if env.scope == "team" and info.scope in ("project", "perso") or env.scope == "project" and info.scope == "perso":
        issues.append(_issue("P_SCOPE_MISMATCH", wid,
                             f"Une page {'d equipe' if env.scope == 'team' else 'de projet'} ne peut pas lancer le flow "
                             f"{info.scope} `{name}` : les autres postes ne le voient pas.",
                             f"A {env.scope} page cannot run the {info.scope} flow `{name}`: other computers do not see it.",
                             {"kind": "pick_flow", "args": {"widget": wid}}))
    return info


def _buttons_of(flow: Flow) -> List[str]:
    from flux_flows.model import iter_nodes

    return [str(n.params.get("button_id")) for _, n in iter_nodes(flow)
            if n.type == "event.button" and n.params.get("button_id")]


def _check_buttons(page: Page, env: PageEnv, issues: List[PageIssue]) -> None:
    widgets = list(iter_widgets(page))
    buttons = [w for w in widgets if w.kind == "button"]
    has_data = any(w.kind in DATA_KINDS for w in widgets)
    if not buttons and any(w.kind in VALUE_KINDS for w in widgets) and not has_data:
        issues.append(_issue("P_NO_BUTTON", None, "Cette page n'a aucun bouton : les champs ne declenchent rien.",
                             "This page has no button: the fields trigger nothing.", {"kind": "add_button", "args": {}}))
    flows_seen: Dict[str, Optional[FlowInfo]] = {}
    for b in buttons:
        if b.on_click is None:
            issues.append(_issue("P_BUTTON_NO_FLOW", b.id,
                                 f"Le bouton \"{b.label or b.id}\" ne lance aucun flow : choisis un flow dans \"Au clic\".",
                                 f"The button \"{b.label or b.id}\" runs no flow: pick one in \"On click\".",
                                 {"kind": "pick_flow", "args": {"widget": b.id}}))
            continue
        name = b.on_click.flow
        info = _check_flow_ref(env, b.id, name, issues)
        flows_seen[name] = info
        if info is None:
            continue
        if b.on_click.button_id not in _buttons_of(info.flow):
            issues.append(_issue("P_BUTTON_MISSING_IN_FLOW", b.id,
                                 f"Le flow `{name}` n'a pas de node Bouton `{b.on_click.button_id}` : la page ne peut pas le declencher.",
                                 f"The flow `{name}` has no Button node `{b.on_click.button_id}`: the page cannot trigger it.",
                                 {"kind": "add_button_node", "args": {"flow": name, "button_id": b.on_click.button_id}}))
        if info.valid is False:
            issues.append(_issue("P_FLOW_INVALID", b.id,
                                 f"Le flow `{name}` est invalide : le bouton ne peut pas le lancer.",
                                 f"The flow `{name}` is invalid: the button cannot run it.",
                                 {"kind": "open_flow", "args": {"flow": name}}))
        elif not info.active:
            issues.append(_issue("P_FLOW_INACTIVE", b.id,
                                 f"Le flow `{name}` n'est pas actif : le bouton restera grise.",
                                 f"The flow `{name}` is not active: the button stays greyed out.",
                                 {"kind": "activate_flow", "args": {"flow": name}}))
    # Fields bound to the flows of the buttons.
    for w in widgets:
        if w.kind not in VALUE_KINDS:
            continue
        if w.kind == "select" and not w.options:
            issues.append(_issue("P_OPTIONS_EMPTY", w.id, f"La liste de choix \"{w.label or w.id}\" n'a aucune option.",
                                 f"The choice list \"{w.label or w.id}\" has no option.",
                                 {"kind": "add_option", "args": {"widget": w.id}}))
        if w.bind is None:
            continue
        name = w.bind.flow
        info = flows_seen[name] if name in flows_seen else _check_flow_ref(env, w.id, name, issues)
        flows_seen.setdefault(name, info)
        if info is None:
            continue
        params = {i.id: i for i in info.flow.interface.inputs}
        param = params.get(w.bind.param)
        if param is None:
            guess = _closest(w.bind.param, list(params))
            fr = f"Le flow `{name}` n'expose pas de parametre `{w.bind.param}`. Disponibles : " \
                 f"{', '.join(f'`{p}`' for p in params) or 'aucun'}." + (f" Tu voulais `{guess}` ?" if guess else "")
            en = f"The flow `{name}` exposes no parameter `{w.bind.param}`." + (f" Did you mean `{guess}`?" if guess else "")
            issues.append(_issue("P_PARAM_NOT_FOUND", w.id, fr, en,
                                 {"kind": "bind", "args": {"widget": w.id, "param": guess}} if guess else None))
            continue
        if param.type not in FEEDS[w.kind]:
            want = KIND_FOR_TYPE.get(param.type)
            fr = f"Le champ `{w.id}` ({w.kind}) ne peut pas alimenter `{param.id}` ({param.type})" + \
                 (f" : utilise un champ {want}." if want else " : ce parametre se branche dans le flow, pas dans une page.")
            en = f"The field `{w.id}` ({w.kind}) cannot feed `{param.id}` ({param.type})."
            issues.append(_issue("P_TYPE_MISMATCH", w.id, fr, en,
                                 {"kind": "set_kind", "args": {"widget": w.id, "kind": want}} if want else None))
    # Interface inputs of the launched flows that no field fills.
    bound = {(w.bind.flow, w.bind.param) for w in widgets if w.kind in VALUE_KINDS and w.bind}
    for b in buttons:
        if b.on_click is None or flows_seen.get(b.on_click.flow) is None:
            continue
        name = b.on_click.flow
        for param in flows_seen[name].flow.interface.inputs:
            if (name, param.id) in bound or param.type not in KIND_FOR_TYPE:
                continue
            bound.add((name, param.id))
            if param.default is None:
                issues.append(_issue("P_REQUIRED_UNBOUND", b.id,
                                     f"`{param.id}` est obligatoire, sans valeur par defaut et sans champ dans cette page.",
                                     f"`{param.id}` is required, has no default and no field in this page.",
                                     {"kind": "add_bound_field", "args": {"flow": name, "param": param.id}}))
            else:
                issues.append(_issue("P_PARAM_UNBOUND", b.id,
                                     f"`{param.id}` n'a pas de champ dans cette page : la valeur par defaut sera utilisee.",
                                     f"`{param.id}` has no field in this page: the default value will be used.",
                                     {"kind": "add_bound_field", "args": {"flow": name, "param": param.id}}))


def _field_check(w: Widget, spec: DataSpec, prop: str, types: Tuple[str, ...], issues: List[PageIssue],
                 required: bool = False) -> None:
    name = getattr(w, prop)
    fields = {f.id: f for f in spec.fields}
    if name is None:
        if required:
            choice = next((f.id for f in spec.fields if f.type in types), None)
            issues.append(_issue("P_FIELD_NOT_FOUND", w.id,
                                 f"{w.kind} `{w.id}` : choisis le champ `{prop}` de la collection `{spec.id}`.",
                                 f"{w.kind} `{w.id}`: pick the `{prop}` field of the collection `{spec.id}`.",
                                 {"kind": "set_prop", "args": {"widget": w.id, prop: choice}} if choice else None))
        return
    field = fields.get(name)
    if field is None:
        guess = _closest(name, list(fields))
        issues.append(_issue("P_FIELD_NOT_FOUND", w.id,
                             f"La collection `{spec.id}` n'a pas de champ `{name}`." + (f" Tu voulais `{guess}` ?" if guess else ""),
                             f"The collection `{spec.id}` has no field `{name}`.",
                             {"kind": "set_prop", "args": {"widget": w.id, prop: guess}} if guess else None))
    elif types and field.type not in types:
        issues.append(_issue("P_FIELD_TYPE", w.id,
                             f"{w.kind} `{w.id}` : le champ `{name}` est de type {field.type}, attendu {' ou '.join(types)}.",
                             f"{w.kind} `{w.id}`: the field `{name}` is {field.type}, expected {' or '.join(types)}."))


def _check_sources(page: Page, env: PageEnv, issues: List[PageIssue]) -> None:
    specs = {d.id: d for d in page.data}
    used: set = set()
    for w in iter_widgets(page):
        if w.kind not in DATA_KINDS:
            continue
        src = w.source
        if src is None:
            issues.append(_issue("P_SOURCE_MISSING", w.id, f"{w.kind} `{w.id}` : choisis la source de ses donnees.",
                                 f"{w.kind} `{w.id}`: pick its data source.", {"kind": "pick_source", "args": {"widget": w.id}}))
            continue
        if src.builtin is not None:
            if w.kind != "members":
                issues.append(_issue("P_SOURCE_KIND", w.id, f"La source integree `{src.builtin}` va avec le widget members.",
                                     f"The builtin source `{src.builtin}` goes with the members widget."))
            continue
        if src.flow is not None:
            if w.kind in ("board", "members"):
                issues.append(_issue("P_SOURCE_KIND", w.id, f"{w.kind} `{w.id}` lit une collection, pas la sortie d'un flow.",
                                     f"{w.kind} `{w.id}` reads a collection, not a flow output."))
                continue
            info = _check_flow_ref(env, w.id, src.flow, issues)
            if info is not None and src.output not in {o.id for o in info.flow.interface.outputs}:
                issues.append(_issue("P_OUTPUT_NOT_FOUND", w.id, f"Le flow `{src.flow}` n'a pas de sortie `{src.output}`.",
                                     f"The flow `{src.flow}` has no output `{src.output}`."))
            continue
        spec = specs.get(src.data)
        if spec is None:
            guess = _closest(src.data, list(specs))
            issues.append(_issue("P_SOURCE_NOT_FOUND", w.id,
                                 f"La page n'a pas de collection `{src.data}`." + (f" Tu voulais `{guess}` ?" if guess else ""),
                                 f"The page has no collection `{src.data}`.",
                                 {"kind": "set_source", "args": {"widget": w.id, "data": guess}} if guess
                                 else {"kind": "add_data", "args": {"id": src.data}}))
            continue
        used.add(spec.id)
        want = DATA_SOURCE_KINDS.get(w.kind)
        if w.kind == "members" or (want and spec.kind != want):
            issues.append(_issue("P_SOURCE_KIND", w.id,
                                 f"{w.kind} `{w.id}` ne sait pas lire la collection {spec.kind} `{spec.id}`.",
                                 f"{w.kind} `{w.id}` cannot read the {spec.kind} collection `{spec.id}`."))
            continue
        if w.kind == "feed":
            _field_check(w, spec, "field", ("str", "text"), issues, required=w.field is None
                         and not any(f.id == "text" for f in spec.fields))
            _field_check(w, spec, "group_by", ("str", "select", "user"), issues)
        elif w.kind == "cards":
            _field_check(w, spec, "title", ("str", "text"), issues)
            _field_check(w, spec, "group_by", ("str", "select", "user", "bool"), issues)
        elif w.kind == "calendar":
            _field_check(w, spec, "date", DATE_TYPES, issues,
                         required=w.date is None and not any(f.type in DATE_TYPES for f in spec.fields))
            _field_check(w, spec, "end", DATE_TYPES, issues)
            _field_check(w, spec, "title", ("str", "text"), issues)
        elif w.kind == "table":
            for col in w.columns or []:
                if col not in {f.id for f in spec.fields}:
                    issues.append(_issue("P_FIELD_NOT_FOUND", w.id, f"La collection `{spec.id}` n'a pas de champ `{col}`.",
                                         f"The collection `{spec.id}` has no field `{col}`."))
    for spec in page.data:
        if spec.id not in used:
            issues.append(_issue("P_DATA_UNUSED", None, f"La collection `{spec.id}` n'est affichee par aucun widget.",
                                 f"The collection `{spec.id}` is shown by no widget."))


def validate_page(page: Page, env: Optional[PageEnv] = None) -> List[PageIssue]:
    """Every P_* issue of *page* (04 §8). Links to flows are checked when env has a flow_lookup."""
    env = env or PageEnv()
    issues: List[PageIssue] = []
    _check_ids(page, issues)
    _check_rows(page, issues)
    _check_buttons(page, env, issues)
    _check_sources(page, env, issues)
    return issues


def errors(issues: List[PageIssue]) -> List[PageIssue]:
    return [i for i in issues if i.level == ERROR]

