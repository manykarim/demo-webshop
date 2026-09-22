"""The semantic snapshot of a rendered page (drift-coverage Decision 7).

The snapshot is everything the stage contract promises never changes: what a
person reads, what an assistive technology announces, and where the page takes
them. It deliberately contains no element id, no class name and no ``data-test``
value, so a render of stage 2, 3 or 4 has the *same* snapshot as stage 1 of the
same build while every locator hook around it has moved.

A snapshot is the document-order sequence of:

* normalized visible text - the subtrees of ``script``, ``style`` and
  ``template`` contribute nothing, because none of them is visible;
* the explicit (``role``) or implicit role of an element, with the level of a
  heading;
* its accessible name, resolved in this order: ``aria-labelledby`` (within the
  same document), ``aria-label``, ``label[for]`` or a wrapping ``label``,
  ``alt``, the submit button's ``value``, and finally the name from content for
  the roles that take one;
* a form field's ``name`` and ``type``, and a form's ``action`` and ``method``;
* hyperlink targets: the ``href`` of ``a[href]`` and ``area[href]``. Resource
  URLs (``link[href]``, ``script[src]``, ``img[src]``) are *not* part of the
  snapshot, because the stylesheet href follows the drift by design
  (Decision 5);
* the content data attributes, which the stable contract keeps: ``data-product``,
  ``data-product-name``, ``data-category`` and ``data-chat-prompt``.

An element that contributes none of these - a role-less ``div`` or ``span``
wrapper, for example, which is exactly what stage 4 adds - produces no entry at
all, so re-nesting content cannot change a snapshot.

``snapshot()`` takes an optional list of ``(regex, placeholder)`` replacements,
applied to text - including accessible names, which are text - and to ``href``
values, for the values that are unique per order. Without them the snapshot is
exactly as described above.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.element import PreformattedString

__all__ = [
    "CONTENT_DATA_ATTRIBUTES",
    "ORDER_RESULT_MASK",
    "Document",
    "Snapshot",
    "SnapshotEntry",
    "accessible_name",
    "document",
    "normalize_text",
    "snapshot",
    "visible_text",
]

#: One line of a snapshot: ``("text", value)`` or ``("node", "role=…", …)``.
SnapshotEntry = tuple[str, ...]

#: A whole snapshot: the entries in document order.
Snapshot = tuple[SnapshotEntry, ...]

#: The ``data-*`` attributes that carry content rather than a lookup marker and
#: are therefore part of the stable contract (design Decision 3 and 4).
CONTENT_DATA_ATTRIBUTES: tuple[str, ...] = (
    "data-product",
    "data-product-name",
    "data-category",
    "data-chat-prompt",
)

#: The replacements that make two successful checkout renders comparable: the
#: order number and the order id are unique per order and appear in the
#: confirmation message and in both document links.
ORDER_RESULT_MASK: list[tuple[str, str]] = [
    (r"ORD-[0-9A-F]{8}", "ORD-<n>"),
    (r"/api/docs/orders/\d+/", "/api/docs/orders/<id>/"),
]

#: Subtrees that contribute nothing: none of them is visible content.
_INVISIBLE_SUBTREES: frozenset[str] = frozenset({"script", "style", "template"})

#: The HTML parser backend. ``html.parser`` is pure Python, needs no native
#: wheel and tolerates the malformed markup a template can produce.
_PARSER = "html.parser"

_WHITESPACE = re.compile(r"\s+")

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

#: Implicit ARIA roles of the elements this shop renders. Elements that map to
#: no role (``div``, ``span``, ``picture``, ``source``, ``svg``, ``path``,
#: ``label``, ``br``) are simply absent.
_IMPLICIT_ROLES: Mapping[str, str] = {
    "article": "article",
    "aside": "complementary",
    "button": "button",
    "dd": "definition",
    "details": "group",
    "dialog": "dialog",
    "dt": "term",
    "fieldset": "group",
    "figure": "figure",
    "footer": "contentinfo",
    "form": "form",
    "header": "banner",
    "hr": "separator",
    "li": "listitem",
    "main": "main",
    "menu": "list",
    "meter": "meter",
    "nav": "navigation",
    "ol": "list",
    "optgroup": "group",
    "option": "option",
    "output": "status",
    "p": "paragraph",
    "progress": "progressbar",
    "search": "search",
    "section": "region",
    "summary": "button",
    "table": "table",
    "tbody": "rowgroup",
    "td": "cell",
    "textarea": "textbox",
    "tfoot": "rowgroup",
    "th": "columnheader",
    "thead": "rowgroup",
    "tr": "row",
    "ul": "list",
}

#: Implicit roles of ``<input>``, by ``type``. ``hidden`` maps to no role.
_INPUT_ROLES: Mapping[str, str] = {
    "button": "button",
    "checkbox": "checkbox",
    "color": "textbox",
    "date": "textbox",
    "email": "textbox",
    "file": "textbox",
    "image": "button",
    "number": "spinbutton",
    "password": "textbox",
    "radio": "radio",
    "range": "slider",
    "reset": "button",
    "search": "searchbox",
    "submit": "button",
    "tel": "textbox",
    "text": "textbox",
    "time": "textbox",
    "url": "textbox",
}

#: Roles whose accessible name may be computed from the element's contents.
_NAME_FROM_CONTENT: frozenset[str] = frozenset(
    {
        "button",
        "cell",
        "checkbox",
        "columnheader",
        "heading",
        "link",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "option",
        "radio",
        "row",
        "rowheader",
        "switch",
        "tab",
        "tooltip",
        "treeitem",
    }
)

#: Form controls, for the ``name``/``type`` facets and for label association.
_FORM_CONTROLS: frozenset[str] = frozenset({"input", "select", "textarea"})

#: The facets of one node entry, in the order they are written.
_FACET_ORDER: tuple[str, ...] = (
    "role",
    "level",
    "name",
    "field-name",
    "type",
    "action",
    "method",
    "href",
    *CONTENT_DATA_ATTRIBUTES,
)


def _attr(tag: Tag, name: str) -> str:
    """The value of ``name`` on ``tag`` as a plain string ("" when absent)."""
    value = tag.get(name)
    if value is None:
        return ""
    if isinstance(value, list):  # a multi-valued attribute such as ``class``
        return " ".join(str(item) for item in value)
    return str(value)


def normalize_text(text: str) -> str:
    """Collapse runs of whitespace and strip the ends."""
    return _WHITESPACE.sub(" ", text).strip()


def _implicit_role(tag: Tag) -> str:
    """The implicit ARIA role of ``tag``, or "" when it has none."""
    name = tag.name.lower()
    if name in {"a", "area"}:
        return "link" if tag.has_attr("href") else ""
    if name == "input":
        return _INPUT_ROLES.get(_attr(tag, "type").lower() or "text", "")
    if name == "select":
        multiple = tag.has_attr("multiple")
        size = _attr(tag, "size")
        return "listbox" if multiple or (size.isdigit() and int(size) > 1) else "combobox"
    if name == "img":
        # An empty ``alt`` is the author saying "decorative": no role, no name.
        return "img" if _attr(tag, "alt") or not tag.has_attr("alt") else ""
    if len(name) == 2 and name[0] == "h" and name[1].isdigit():
        return "heading"
    return _IMPLICIT_ROLES.get(name, "")


def _role(tag: Tag) -> str:
    """The role of ``tag``: the explicit one wins over the implicit one."""
    explicit = normalize_text(_attr(tag, "role"))
    if explicit:
        # ARIA allows a fallback list; the first token that is a role wins.
        return explicit.split(" ")[0]
    return _implicit_role(tag)


def _heading_level(tag: Tag) -> str:
    """The heading level of ``tag`` as a string, or "" when it is not one."""
    explicit = _attr(tag, "aria-level")
    if explicit.isdigit():
        return explicit
    name = tag.name.lower()
    if len(name) == 2 and name[0] == "h" and name[1].isdigit():
        return name[1]
    return ""


# ---------------------------------------------------------------------------
# Text and accessible names
# ---------------------------------------------------------------------------


def _text_nodes(node: Tag) -> Iterator[str]:
    """Every visible text node inside ``node``, in document order."""
    for child in node.children:
        if isinstance(child, Tag):
            if child.name.lower() in _INVISIBLE_SUBTREES:
                continue
            yield from _text_nodes(child)
        elif isinstance(child, NavigableString) and not isinstance(child, PreformattedString):
            yield str(child)


def visible_text(node: Tag) -> str:
    """The normalized visible text of ``node``, its own subtree included."""
    return normalize_text("".join(_text_nodes(node)))


@dataclass(frozen=True)
class Document:
    """The two id indexes a name computation needs, built once per snapshot.

    ``by_id`` resolves ``aria-labelledby`` references and ``labels_by_for``
    resolves ``label[for]``. Both are keyed by ids that drift, and both are
    looked up by the *same* drifted id in the same document, so the resulting
    name is stage-independent - which is exactly what the stage contract
    promises and what a broken ``for`` target must break.
    """

    by_id: Mapping[str, Tag]
    labels_by_for: Mapping[str, Tag]


def document(soup: Tag) -> Document:
    """Index ``soup`` for name resolution."""
    by_id: dict[str, Tag] = {}
    for element in soup.find_all(attrs={"id": True}):
        by_id.setdefault(_attr(element, "id"), element)

    labels_by_for: dict[str, Tag] = {}
    for label in soup.find_all("label"):
        target = _attr(label, "for")
        if target:
            labels_by_for.setdefault(target, label)

    return Document(by_id=by_id, labels_by_for=labels_by_for)


def _labelled_by(tag: Tag, doc: Document) -> str:
    """The name from ``aria-labelledby``, resolved inside the same document.

    The *ids* drift; the text they point at does not, which is precisely what
    makes this part of the snapshot stable across stages.
    """
    references = _attr(tag, "aria-labelledby").split()
    if not references:
        return ""
    parts = [visible_text(doc.by_id[ref]) for ref in references if ref in doc.by_id]
    return normalize_text(" ".join(part for part in parts if part))


def _label_text(tag: Tag, doc: Document) -> str:
    """The name a ``<label>`` gives to the form control ``tag``."""
    control_id = _attr(tag, "id")
    label = doc.labels_by_for.get(control_id) if control_id else None
    if label is not None:
        return visible_text(label)
    wrapping = tag.find_parent("label")
    if wrapping is not None:
        return visible_text(wrapping)
    return ""


def accessible_name(tag: Tag, doc: Document, role: str = "") -> str:
    """The accessible name of ``tag``, by the precedence of the spec."""
    name = _labelled_by(tag, doc)
    if name:
        return name

    name = normalize_text(_attr(tag, "aria-label"))
    if name:
        return name

    tag_name = tag.name.lower()
    if tag_name in _FORM_CONTROLS:
        name = _label_text(tag, doc)
        if name:
            return name
        if tag_name == "input" and _attr(tag, "type").lower() in {"submit", "reset", "button"}:
            return normalize_text(_attr(tag, "value"))
        return ""

    if tag_name == "img":
        return normalize_text(_attr(tag, "alt"))

    if role in _NAME_FROM_CONTENT:
        return visible_text(tag)

    return ""


# ---------------------------------------------------------------------------
# The snapshot
# ---------------------------------------------------------------------------


def _compile(replacements: Sequence[tuple[str, str]] | None) -> tuple[tuple[re.Pattern[str], str], ...]:
    return tuple((re.compile(pattern), placeholder) for pattern, placeholder in replacements or ())


def _masked(value: str, replacements: Iterable[tuple[re.Pattern[str], str]]) -> str:
    for pattern, placeholder in replacements:
        value = pattern.sub(placeholder, value)
    return value


def _facets(
    tag: Tag,
    doc: Document,
    replacements: Iterable[tuple[re.Pattern[str], str]],
) -> dict[str, str]:
    """Every snapshot facet ``tag`` contributes, keyed by facet name."""
    facets: dict[str, str] = {}
    tag_name = tag.name.lower()

    role = _role(tag)
    if role:
        facets["role"] = role
        level = _heading_level(tag) if role == "heading" else ""
        if level:
            facets["level"] = level

    name = accessible_name(tag, doc, role)
    if name:
        facets["name"] = _masked(name, replacements)

    if tag_name in _FORM_CONTROLS or tag_name == "button":
        field_name = _attr(tag, "name")
        if field_name:
            facets["field-name"] = field_name
        if tag_name == "input":
            facets["type"] = (_attr(tag, "type") or "text").lower()
        elif tag_name == "button":
            facets["type"] = (_attr(tag, "type") or "submit").lower()

    if tag_name == "form":
        facets["action"] = _attr(tag, "action")
        facets["method"] = (_attr(tag, "method") or "get").lower()

    if tag_name in {"a", "area"} and tag.has_attr("href"):
        facets["href"] = _masked(_attr(tag, "href"), replacements)

    for attribute in CONTENT_DATA_ATTRIBUTES:
        if tag.has_attr(attribute):
            facets[attribute] = _masked(_attr(tag, attribute), replacements)

    return facets


def _entry(facets: Mapping[str, str]) -> SnapshotEntry:
    return ("node", *(f"{key}={facets[key]}" for key in _FACET_ORDER if key in facets))


def _walk(
    node: Tag,
    doc: Document,
    replacements: Iterable[tuple[re.Pattern[str], str]],
    out: list[SnapshotEntry],
) -> None:
    for child in node.children:
        if isinstance(child, Tag):
            if child.name.lower() in _INVISIBLE_SUBTREES:
                continue
            facets = _facets(child, doc, replacements)
            if facets:
                out.append(_entry(facets))
            _walk(child, doc, replacements, out)
        elif isinstance(child, NavigableString) and not isinstance(child, PreformattedString):
            text = _masked(normalize_text(str(child)), replacements)
            if text:
                out.append(("text", text))


def snapshot(html: str, replacements: Sequence[tuple[str, str]] | None = None) -> Snapshot:
    """The semantic snapshot of ``html``.

    ``replacements`` is an optional list of ``(regex, placeholder)`` pairs
    applied to text (accessible names included, because a name is text) and to
    ``href`` values - see :data:`ORDER_RESULT_MASK`. Without it the snapshot is
    unchanged.
    """
    soup = BeautifulSoup(html, _PARSER)
    entries: list[SnapshotEntry] = []
    _walk(soup, document(soup), _compile(replacements), entries)
    return tuple(entries)
