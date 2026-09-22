"""Story set, index and conformance record: parser and offline guard (design D1, D2, D4).

The parser reads three kinds of documents under ``docs/user-stories/``:

* **story files** - every top-level file whose name matches
  :data:`STORY_FILE_PATTERN`; their ``### AC-<n>: <title>`` headings and their
  ``## Revisions`` table;
* **the index** ``README.md`` - the story table of its ``## Stories`` section and
  the withdrawn table of its ``## Withdrawn criteria`` section. Tables are read
  per section and never inside fenced code blocks, so the example table of the
  ID rules is ignored;
* **the record** ``CONFORMANCE.md`` - its version sections (``## Unreleased`` or
  a ``## workshop-<id>`` tag; every other ``##`` section is prose), their
  header lines, their criterion rows and their ``### Planted bugs without
  criterion`` table.

The guard rules are the ``check_*(docs_root, tests_root)`` functions at the end.
Each returns a list of problems (empty when the rule holds), naming the
offending criterion, flag, section or file, so the same rules run on the
repository and on temporary copies. ``docs_root`` is the story directory and
``tests_root`` the ``backend/tests`` directory whose ``conformance/`` holds the
story modules.

Nothing from ``backend.app`` is imported at module level; the planted-bug
registry and the presets are imported inside the functions that need them.
"""
from __future__ import annotations

import ast
import os
import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Names and patterns
# ---------------------------------------------------------------------------

#: Story files in scope (design D1): top-level files only.
STORY_FILE_PATTERN = re.compile(r"^(WEB|API|AI)-\d{3}_.+\.md$")
#: A story ID such as ``WEB-006``.
STORY_ID_PATTERN = re.compile(r"^(?:WEB|API|AI)-\d{3}$")
#: A criterion ID such as ``WEB-006_AC-7``.
CRITERION_ID_PATTERN = re.compile(r"^((?:WEB|API|AI)-\d{3})_AC-([1-9]\d*)$")
#: A well-formed criterion heading.
AC_HEADING_PATTERN = re.compile(r"^### AC-([1-9]\d*): (\S.*?)\s*$")
#: Any heading that looks like it is meant to be a criterion heading.
AC_CANDIDATE_PATTERN = re.compile(r"^\s{0,3}#+\s*AC(?:[-\s:]|\d|$)", re.IGNORECASE)
#: A version section name in the record: ``Unreleased`` or a workshop tag.
VERSION_NAME_PATTERN = re.compile(r"^(?:Unreleased|workshop-[A-Za-z0-9][A-Za-z0-9._-]*)$")
#: Story modules of the conformance suite (design D4 check 3).
STORY_MODULE_PATTERN = re.compile(r"^test_(web|api|ai)_.+\.py$")
#: The story a story module belongs to: ``test_web_002_...`` -> ``WEB-002``.
STORY_MODULE_STORY_PATTERN = re.compile(r"^test_(web|api|ai)_(\d{3})(?:_.*)?\.py$")
#: A link in a reason: a Markdown link or a bare URL.
LINK_PATTERN = re.compile(r"\[[^\]]+\]\([^)\s]+\)|https?://\S+")

INDEX_FILE = "README.md"
RECORD_FILE = "CONFORMANCE.md"
CONFORMANCE_DIR = "conformance"
UNRELEASED = "Unreleased"
NO_CRITERION_HEADING = "Planted bugs without criterion"
RELEASE_ENV = "CONFORMANCE_RELEASE"

#: Every status a row may have (design D2).
STATUSES: tuple[str, ...] = ("conforms", "app-fixed", "story-corrected", "planted-bug", "pending")
#: Statuses whose ``Note`` must not be empty.
NOTE_REQUIRED: tuple[str, ...] = ("app-fixed", "story-corrected", "planted-bug")
PENDING = "pending"
PLANTED_BUG = "planted-bug"


class RecordLookupError(LookupError):
    """``lookup()`` found no row, or more than one, for a criterion."""


class _FromEnvironment:
    """Sentinel: read release mode from ``CONFORMANCE_RELEASE``."""

    def __repr__(self) -> str:
        return "FROM_ENV"


#: Default of the ``release`` keyword of the release-aware checks.
FROM_ENV = _FromEnvironment()


def release_tag(release: str | None | _FromEnvironment = FROM_ENV) -> str | None:
    """The release tag in effect, or ``None`` when release mode is off."""
    if isinstance(release, _FromEnvironment):
        return os.environ.get(RELEASE_ENV, "").strip() or None
    return (release or "").strip() or None


# ---------------------------------------------------------------------------
# Markdown primitives
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_SEPARATOR_CELL = re.compile(r"^:?-+:?$")
_LINK_TARGET = re.compile(r"^\[[^\]]*\]\(([^)\s]+)\)$")


@dataclass(frozen=True)
class Line:
    number: int
    text: str


@dataclass(frozen=True)
class TableRow:
    cells: tuple[str, ...]
    line: int

    def cell(self, index: int) -> str:
        return self.cells[index] if index < len(self.cells) else ""


@dataclass(frozen=True)
class Table:
    header: tuple[str, ...]
    rows: tuple[TableRow, ...]
    line: int

    def column(self, name: str) -> int | None:
        wanted = name.strip().lower()
        for index, title in enumerate(self.header):
            if title.strip().lower() == wanted:
                return index
        return None

    def has_columns(self, *names: str) -> bool:
        return all(self.column(name) is not None for name in names)


def content_lines(text: str) -> list[Line]:
    """The lines of ``text`` outside fenced code blocks."""
    lines: list[Line] = []
    fence: str | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        match = _FENCE.match(raw)
        if fence is None:
            if match:
                fence = match.group(1)
                continue
            lines.append(Line(number, raw))
        elif match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
            if not raw.strip()[len(match.group(1)):].strip():
                fence = None
    return lines


def split_cells(line: str) -> tuple[str, ...]:
    """The cells of a table line; ``\\|`` is an escaped pipe inside a cell."""
    body = line.strip()
    body = body.removeprefix("|")
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    cells = re.split(r"(?<!\\)\|", body)
    return tuple(cell.strip().replace("\\|", "|") for cell in cells)


def _is_separator(line: str) -> bool:
    cells = split_cells(line)
    return bool(cells) and all(_SEPARATOR_CELL.match(cell) for cell in cells)


def tables(lines: Sequence[Line]) -> list[Table]:
    """The pipe tables in ``lines``; a table line starts with ``|`` in column 1."""
    found: list[Table] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if (
            line.text.startswith("|")
            and index + 1 < len(lines)
            and lines[index + 1].text.startswith("|")
            and _is_separator(lines[index + 1].text)
        ):
            header = split_cells(line.text)
            rows: list[TableRow] = []
            index += 2
            while index < len(lines) and lines[index].text.startswith("|"):
                rows.append(TableRow(split_cells(lines[index].text), lines[index].number))
                index += 1
            found.append(Table(header, tuple(rows), line.number))
            continue
        index += 1
    return found


@dataclass(frozen=True)
class Section:
    """A ``##`` section: its title and the lines up to the next ``##`` heading."""

    title: str
    line: int
    lines: tuple[Line, ...]


def sections(text: str) -> list[Section]:
    """The ``##`` sections of ``text``, outside fenced code blocks."""
    found: list[Section] = []
    title: str | None = None
    start = 0
    body: list[Line] = []
    for line in content_lines(text):
        match = re.match(r"^##\s+(?!#)(.*?)\s*#*\s*$", line.text)
        if match:
            if title is not None:
                found.append(Section(title, start, tuple(body)))
            title, start, body = match.group(1).strip(), line.number, []
        elif title is not None:
            body.append(line)
    if title is not None:
        found.append(Section(title, start, tuple(body)))
    return found


def _subsections(lines: Sequence[Line]) -> list[tuple[str | None, int, list[Line]]]:
    """Split a section body at its ``###`` headings; the first part has no title."""
    parts: list[tuple[str | None, int, list[Line]]] = [(None, 0, [])]
    for line in lines:
        match = re.match(r"^###\s+(?!#)(.*?)\s*#*\s*$", line.text)
        if match:
            parts.append((match.group(1).strip(), line.number, []))
        else:
            parts[-1][2].append(line)
    return parts


def _link_target(cell: str) -> str:
    match = _LINK_TARGET.match(cell.strip())
    if match:
        return match.group(1)
    return cell.strip().strip("`")


def split_flags(cell: str) -> tuple[str, ...]:
    """A ``Flag`` cell as flag keys: comma-separated, backticks dropped."""
    return tuple(part.strip().strip("`").strip() for part in cell.split(",") if part.strip().strip("`").strip())


# ---------------------------------------------------------------------------
# Story files
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Criterion:
    story: str
    number: int
    title: str
    line: int

    @property
    def id(self) -> str:
        return criterion_id(self.story, self.number)


@dataclass(frozen=True)
class MalformedHeading:
    line: int
    text: str


@dataclass(frozen=True)
class Revision:
    version: str
    criterion: str
    original: str
    new: str
    reason: str
    line: int


@dataclass(frozen=True)
class Story:
    id: str
    file_name: str
    headings: tuple[Criterion, ...]
    malformed: tuple[MalformedHeading, ...]
    revisions: tuple[Revision, ...]
    text: str

    @property
    def numbers(self) -> list[int]:
        """The active criterion numbers, ascending, duplicates removed."""
        return sorted({heading.number for heading in self.headings})

    @property
    def active_ids(self) -> list[str]:
        return [criterion_id(self.id, number) for number in self.numbers]


def criterion_id(story: str, number: int) -> str:
    return f"{story}_AC-{number}"


def parse_criterion_id(value: str) -> tuple[str, int] | None:
    match = CRITERION_ID_PATTERN.match(value.strip())
    return (match.group(1), int(match.group(2))) if match else None


def criterion_sort_key(value: str) -> tuple[str, int, str]:
    parsed = parse_criterion_id(value)
    return (parsed[0], parsed[1], "") if parsed else ("~", 0, value)


def story_id_of(file_name: str) -> str:
    if not STORY_FILE_PATTERN.match(file_name):
        raise ValueError(f"{file_name} is not a story file name")
    return file_name.split("_", 1)[0]


def parse_story(text: str, file_name: str) -> Story:
    """Parse one story file; ``file_name`` gives the story ID."""
    story = story_id_of(file_name)
    headings: list[Criterion] = []
    malformed: list[MalformedHeading] = []
    for line in content_lines(text):
        match = AC_HEADING_PATTERN.match(line.text)
        if match:
            headings.append(Criterion(story, int(match.group(1)), match.group(2), line.number))
        elif AC_CANDIDATE_PATTERN.match(line.text):
            malformed.append(MalformedHeading(line.number, line.text.strip()))

    revisions: list[Revision] = []
    for part in sections(text):
        if part.title.lower() != "revisions":
            continue
        for table in tables(part.lines):
            if not table.has_columns("Version", "Criterion"):
                continue
            columns = [table.column(name) for name in ("Version", "Criterion", "Original wording", "New wording", "Reason")]
            for row in table.rows:
                values = [row.cell(column) if column is not None else "" for column in columns]
                revisions.append(Revision(*values, line=row.line))
    return Story(story, file_name, tuple(headings), tuple(malformed), tuple(revisions), text)


def discover_story_files(docs_root: Path) -> list[Path]:
    """The story files in scope: top-level files matching the D1 pattern."""
    if not docs_root.is_dir():
        return []
    return sorted(
        path for path in docs_root.iterdir() if path.is_file() and STORY_FILE_PATTERN.match(path.name)
    )


def load_stories(docs_root: Path) -> list[Story]:
    return [parse_story(path.read_text(encoding="utf-8"), path.name) for path in discover_story_files(docs_root)]


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IndexStory:
    id: str
    title: str
    file: str
    active_criteria: int | None
    raw_count: str
    line: int


@dataclass(frozen=True)
class Withdrawn:
    id: str
    version: str
    reason: str
    replacement: str
    line: int


@dataclass(frozen=True)
class Index:
    stories: tuple[IndexStory, ...]
    withdrawn: tuple[Withdrawn, ...]
    problems: tuple[str, ...]

    @property
    def withdrawn_ids(self) -> set[str]:
        return {entry.id for entry in self.withdrawn}


def _section_table(text: str, title: str, *columns: str) -> tuple[Table | None, str | None]:
    matching = [part for part in sections(text) if part.title.lower() == title.lower()]
    if not matching:
        return None, f"{INDEX_FILE}: no '## {title}' section"
    for table in tables(matching[0].lines):
        if table.has_columns(*columns):
            return table, None
    return None, f"{INDEX_FILE}: '## {title}' has no table with the columns {', '.join(columns)}"


def parse_index(text: str) -> Index:
    """Read the story table and the withdrawn table of the index."""
    problems: list[str] = []
    stories: list[IndexStory] = []
    withdrawn: list[Withdrawn] = []

    table, problem = _section_table(text, "Stories", "ID", "Title", "File", "Active criteria")
    if problem:
        problems.append(problem)
    if table is not None:
        id_col, title_col, file_col, count_col = (
            table.column(name) for name in ("ID", "Title", "File", "Active criteria")
        )
        for row in table.rows:
            raw_count = row.cell(count_col)  # type: ignore[arg-type]
            count = int(raw_count) if raw_count.isdigit() else None
            stories.append(
                IndexStory(
                    id=row.cell(id_col),  # type: ignore[arg-type]
                    title=row.cell(title_col),  # type: ignore[arg-type]
                    file=_link_target(row.cell(file_col)),  # type: ignore[arg-type]
                    active_criteria=count,
                    raw_count=raw_count,
                    line=row.line,
                )
            )

    table, problem = _section_table(
        text, "Withdrawn criteria", "ID", "Version withdrawn", "Reason", "Replacement ID"
    )
    if problem:
        problems.append(problem)
    if table is not None:
        columns = [table.column(name) for name in ("ID", "Version withdrawn", "Reason", "Replacement ID")]
        for row in table.rows:
            values = [row.cell(column) for column in columns]  # type: ignore[arg-type]
            withdrawn.append(Withdrawn(*values, line=row.line))
    return Index(tuple(stories), tuple(withdrawn), tuple(problems))


def load_index(docs_root: Path) -> Index:
    path = docs_root / INDEX_FILE
    if not path.is_file():
        return Index((), (), (f"{INDEX_FILE} is missing",))
    return parse_index(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Conformance record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordRow:
    criterion: str
    status: str
    flags: tuple[str, ...]
    note: str
    line: int


@dataclass(frozen=True)
class NoCriterionRow:
    flag: str
    reason: str
    line: int


@dataclass(frozen=True)
class VersionSection:
    name: str
    line: int
    header_lines: tuple[str, ...]
    rows: tuple[RecordRow, ...]
    no_criterion: tuple[NoCriterionRow, ...]
    has_table: bool

    @property
    def released(self) -> bool:
        return self.name != UNRELEASED


@dataclass(frozen=True)
class Record:
    versions: tuple[VersionSection, ...]
    prose: tuple[str, ...]

    @property
    def top(self) -> VersionSection | None:
        return self.versions[0] if self.versions else None


def _version_section(part: Section) -> VersionSection:
    header_lines: list[str] = []
    rows: list[RecordRow] = []
    no_criterion: list[NoCriterionRow] = []
    has_table = False
    for title, _line, lines in _subsections(part.lines):
        if title is None:
            header_lines = [line.text.strip()[2:].strip() for line in lines if line.text.startswith("- ")]
            for table in tables(lines):
                if not table.has_columns("Criterion", "Status"):
                    continue
                has_table = True
                criterion, status, flag, note = (table.column(name) for name in ("Criterion", "Status", "Flag", "Note"))
                for row in table.rows:
                    rows.append(
                        RecordRow(
                            criterion=row.cell(criterion),  # type: ignore[arg-type]
                            status=row.cell(status),  # type: ignore[arg-type]
                            flags=split_flags(row.cell(flag)) if flag is not None else (),
                            note=row.cell(note) if note is not None else "",
                            line=row.line,
                        )
                    )
        elif title.lower() == NO_CRITERION_HEADING.lower():
            for table in tables(lines):
                if not table.has_columns("Flag", "Reason"):
                    continue
                flag, reason = table.column("Flag"), table.column("Reason")
                for row in table.rows:
                    no_criterion.append(
                        NoCriterionRow(row.cell(flag).strip("`"), row.cell(reason), row.line)  # type: ignore[arg-type]
                    )
    return VersionSection(part.title, part.line, tuple(header_lines), tuple(rows), tuple(no_criterion), has_table)


def parse_record(text: str) -> Record:
    """Split the record into version sections; other ``##`` sections are prose."""
    versions: list[VersionSection] = []
    prose: list[str] = []
    for part in sections(text):
        if VERSION_NAME_PATTERN.match(part.title):
            versions.append(_version_section(part))
        else:
            prose.append(part.title)
    return Record(tuple(versions), tuple(prose))


def load_record(docs_root: Path) -> Record | None:
    path = docs_root / RECORD_FILE
    if not path.is_file():
        return None
    return parse_record(path.read_text(encoding="utf-8"))


def lookup(record: Record, version: str, criterion: str) -> RecordRow:
    """The one row of ``criterion`` in the section of ``version``.

    Raises :class:`RecordLookupError` if the version section is missing or
    duplicated, or if the criterion has no row or more than one.
    """
    matching = [section for section in record.versions if section.name == version]
    if len(matching) != 1:
        raise RecordLookupError(f"{len(matching)} '## {version}' sections in the record; expected exactly one")
    rows = [row for row in matching[0].rows if row.criterion == criterion]
    if len(rows) != 1:
        raise RecordLookupError(f"{criterion}: {len(rows)} rows in '## {version}'; expected exactly one")
    return rows[0]


# ---------------------------------------------------------------------------
# Story modules (design D4 check 3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckMarkers:
    """The literal markers of one check function of a story module."""

    module: str
    name: str
    line: int
    ac: tuple[str, ...]
    planted_bugs: tuple[str, ...]


@dataclass(frozen=True)
class ModuleScan:
    path: Path
    story: str | None
    checks: tuple[CheckMarkers, ...]
    has_conformance_mark: bool
    problems: tuple[str, ...]


def _mark_name(node: ast.AST) -> str | None:
    """``X`` for ``pytest.mark.X`` or ``pytest.mark.X(...)``, else ``None``."""
    target = node.func if isinstance(node, ast.Call) else node
    if (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Attribute)
        and target.value.attr == "mark"
        and isinstance(target.value.value, ast.Name)
        and target.value.value.id == "pytest"
    ):
        return target.attr
    return None


def _literal_argument(node: ast.AST) -> str | None:
    """The one string-literal argument of a marker call, else ``None``."""
    if (
        isinstance(node, ast.Call)
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return node.args[0].value
    return None


def _check_functions(tree: ast.Module) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    found: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            found.append((node.name, node))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test"):
                    found.append((f"{node.name}::{item.name}", item))
    return found


def _pytestmark_values(tree: ast.Module) -> list[ast.AST]:
    values: list[ast.AST] = []
    for node in tree.body:
        value: ast.AST | None = None
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets
        ) or isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "pytestmark":
            value = node.value
        if value is None:
            continue
        values.extend(value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value])
    return values


def scan_module(path: Path, relative: str) -> ModuleScan:
    """Scan one story module statically for its ``ac`` and ``planted_bug`` markers."""
    match = STORY_MODULE_STORY_PATTERN.match(path.name)
    story = f"{match.group(1).upper()}-{match.group(2)}" if match else None
    problems: list[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as error:
        return ModuleScan(path, story, (), False, (f"{relative}: cannot be parsed: {error}",))

    marks = _pytestmark_values(tree)
    has_conformance = any(_mark_name(value) == "conformance" for value in marks)

    accounted: set[int] = set()
    checks: list[CheckMarkers] = []
    for name, function in _check_functions(tree):
        ac_ids: list[str] = []
        flags: list[str] = []
        ac_count = 0
        for decorator in function.decorator_list:
            kind = _mark_name(decorator)
            if kind not in ("ac", "planted_bug"):
                continue
            accounted.add(id(decorator))
            if isinstance(decorator, ast.Call):
                accounted.add(id(decorator.func))
            if kind == "ac":
                ac_count += 1
            value = _literal_argument(decorator)
            if value is None:
                problems.append(
                    f"{relative}::{name} (line {decorator.lineno}): pytest.mark.{kind} needs exactly one "
                    f"string literal argument, found `{ast.unparse(decorator)}`"
                )
                continue
            (ac_ids if kind == "ac" else flags).append(value.strip())
        if ac_count != 1:
            problems.append(f"{relative}::{name} (line {function.lineno}): {ac_count} ac markers; exactly one required")
        checks.append(CheckMarkers(relative, name, function.lineno, tuple(ac_ids), tuple(dict.fromkeys(flags))))

    call_functions = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    for node in ast.walk(tree):
        kind = _mark_name(node) if isinstance(node, (ast.Call, ast.Attribute)) else None
        if kind not in ("ac", "planted_bug") or id(node) in accounted:
            continue
        if isinstance(node, ast.Attribute) and id(node) in call_functions:
            continue  # reported through its call
        problems.append(
            f"{relative} (line {getattr(node, 'lineno', '?')}): pytest.mark.{kind} outside a check "
            f"function's decorators; mark each check directly with string literals"
        )
    return ModuleScan(path, story, tuple(checks), has_conformance, tuple(problems))


def story_module_paths(tests_root: Path) -> list[Path]:
    directory = tests_root / CONFORMANCE_DIR
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.iterdir() if path.is_file() and STORY_MODULE_PATTERN.match(path.name))


def scan_story_modules(tests_root: Path) -> list[ModuleScan]:
    return [
        scan_module(path, f"{CONFORMANCE_DIR}/{path.name}") for path in story_module_paths(tests_root)
    ]


# ---------------------------------------------------------------------------
# Planted-bug registry (imported lazily)
# ---------------------------------------------------------------------------


def registry_flags() -> tuple[str, ...]:
    """The planted-bug flags of the registry, in registry order."""
    from backend.app.core.workshop import PLANTED_BUGS

    return tuple(bug.flag for bug in PLANTED_BUGS)


def preset_bug_flags(preset: str) -> tuple[str, ...]:
    """The ``BUG_*`` flags a preset enables, in registry order."""
    from backend.app.core.workshop import build_presets

    flags = build_presets()[preset]
    return tuple(flag for flag in registry_flags() if flags.get(flag))


# ---------------------------------------------------------------------------
# Guard checks (design D4)
# ---------------------------------------------------------------------------


def _active_ids(stories: Iterable[Story]) -> set[str]:
    return {cid for story in stories for cid in story.active_ids}


def check_headings(docs_root: Path, tests_root: Path) -> list[str]:
    """Check 1: well-formed ``### AC-<n>: <title>`` headings, unique per story."""
    problems: list[str] = []
    for story in load_stories(docs_root):
        for heading in story.malformed:
            problems.append(
                f"{story.file_name}:{heading.line}: malformed criterion heading {heading.text!r}; "
                f"expected '### AC-<n>: <title>'"
            )
        seen: dict[int, int] = {}
        for heading in story.headings:
            if heading.number in seen:
                problems.append(
                    f"{story.file_name}:{heading.line}: duplicate heading {heading.id} "
                    f"(first at line {seen[heading.number]})"
                )
            else:
                seen[heading.number] = heading.line
        if not story.headings and not story.malformed:
            problems.append(f"{story.file_name}: no '### AC-<n>: <title>' heading")
    return problems


def check_no_reuse(docs_root: Path, tests_root: Path) -> list[str]:
    """Check 2: no withdrawn ID appears as a heading again."""
    index = load_index(docs_root)
    problems: list[str] = []
    counts = Counter(entry.id for entry in index.withdrawn)
    for entry in index.withdrawn:
        if not parse_criterion_id(entry.id):
            problems.append(f"{INDEX_FILE}:{entry.line}: withdrawn entry {entry.id!r} is not a criterion ID")
    for withdrawn_id, count in sorted(counts.items()):
        if count > 1:
            problems.append(f"{INDEX_FILE}: {withdrawn_id} is listed {count} times in the withdrawn table")
    withdrawn = index.withdrawn_ids
    for story in load_stories(docs_root):
        for heading in story.headings:
            if heading.id in withdrawn:
                problems.append(
                    f"{story.file_name}:{heading.line}: withdrawn criterion {heading.id} is used again as a heading"
                )
    return problems


def _story_rows_all_pending(record: Record | None, story: Story) -> bool:
    """Whether every row of ``story`` is ``pending`` under a top ``## Unreleased``."""
    if record is None or record.top is None or record.top.name != UNRELEASED:
        return False
    rows = [row for row in record.top.rows if row.criterion.startswith(f"{story.id}_")]
    listed = {row.criterion for row in rows}
    return all(row.status == PENDING for row in rows) and all(cid in listed for cid in story.active_ids)


def check_markers(
    docs_root: Path, tests_root: Path, *, release: str | None | _FromEnvironment = FROM_ENV
) -> list[str]:
    """Check 3: marker coverage of the story modules, and no Robot Framework files."""
    problems: list[str] = []
    if tests_root.is_dir():
        for path in sorted(tests_root.rglob("*")):
            if path.is_file() and path.suffix in (".robot", ".resource"):
                problems.append(
                    f"{path.relative_to(tests_root).as_posix()}: Robot Framework files are not allowed under the tests"
                )

    stories = load_stories(docs_root)
    story_ids = {story.id for story in stories}
    active = _active_ids(stories)
    referenced: set[str] = set()
    with_module: set[str] = set()
    for scan in scan_story_modules(tests_root):
        relative = f"{CONFORMANCE_DIR}/{scan.path.name}"
        problems.extend(scan.problems)
        if not scan.has_conformance_mark:
            problems.append(f"{relative}: no module-level `pytestmark` containing `pytest.mark.conformance`")
        if scan.story is None:
            problems.append(f"{relative}: the file name names no story (expected test_<web|api|ai>_<nnn>_<slug>.py)")
        elif scan.story not in story_ids:
            problems.append(f"{relative}: story module for {scan.story}, which has no story file")
        else:
            with_module.add(scan.story)
        for check in scan.checks:
            for cid in check.ac:
                referenced.add(cid)
                if cid not in active:
                    problems.append(
                        f"{check.module}::{check.name}: pytest.mark.ac({cid!r}) references an unknown criterion {cid}"
                    )

    release_mode = release_tag(release) is not None
    record = load_record(docs_root)
    for story in stories:
        exempt = story.id not in with_module and not release_mode and _story_rows_all_pending(record, story)
        if exempt:
            continue
        for cid in story.active_ids:
            if cid not in referenced:
                where = "its story module" if story.id in with_module else "any story module (none exists)"
                problems.append(f"{cid}: no check in {where} carries pytest.mark.ac({cid!r})")
    return problems


def check_record(docs_root: Path, tests_root: Path) -> list[str]:
    """Check 4: record structure and completeness."""
    record = load_record(docs_root)
    if record is None:
        return [f"{RECORD_FILE} is missing"]
    problems: list[str] = []
    if not record.versions:
        return [f"{RECORD_FILE}: no version section ('## {UNRELEASED}' or '## workshop-<id>')"]

    unreleased = [section for section in record.versions if section.name == UNRELEASED]
    if len(unreleased) > 1:
        lines = ", ".join(str(section.line) for section in unreleased)
        problems.append(f"{RECORD_FILE}: {len(unreleased)} '## {UNRELEASED}' sections (lines {lines}); at most one")
    if unreleased and record.versions[0].name != UNRELEASED:
        problems.append(
            f"{RECORD_FILE}:{unreleased[0].line}: '## {UNRELEASED}' is below the released section "
            f"'## {record.versions[0].name}'; it must be the top version section"
        )
    names = Counter(section.name for section in record.versions if section.released)
    for name, count in sorted(names.items()):
        if count > 1:
            problems.append(f"{RECORD_FILE}: {count} '## {name}' sections")

    for section in record.versions:
        where = f"'## {section.name}'"
        if not section.has_table:
            problems.append(f"{RECORD_FILE}: {where} has no '| Criterion | Status | Flag | Note |' table")
        for row in section.rows:
            label = f"{where} {row.criterion} (line {row.line})"
            if not parse_criterion_id(row.criterion):
                problems.append(f"{label}: {row.criterion!r} is not a criterion ID")
            if row.status not in STATUSES:
                problems.append(f"{label}: unknown status {row.status!r}; allowed: {', '.join(STATUSES)}")
            if row.status == PENDING and section.released:
                problems.append(f"{label}: 'pending' in the released section {where}; only '## {UNRELEASED}' may hold it")
            if row.status == PLANTED_BUG and not row.flags:
                problems.append(f"{label}: planted-bug without a flag")
            if row.status != PLANTED_BUG and row.flags:
                problems.append(
                    f"{label}: flag {', '.join(row.flags)} on status {row.status!r}; Flag is filled only for planted-bug"
                )
            if row.status in NOTE_REQUIRED and not row.note:
                problems.append(f"{label}: {row.status} without a note")

    top = record.versions[0]
    stories = load_stories(docs_root)
    active = _active_ids(stories)
    withdrawn = load_index(docs_root).withdrawn_ids
    counts = Counter(row.criterion for row in top.rows)
    for cid in sorted(active, key=criterion_sort_key):
        if counts[cid] == 0:
            problems.append(f"'## {top.name}': missing row for active criterion {cid}")
        elif counts[cid] > 1:
            problems.append(f"'## {top.name}': duplicate row for {cid} ({counts[cid]} rows)")
    for cid in sorted(counts, key=criterion_sort_key):
        if cid in active:
            continue
        if cid in withdrawn:
            problems.append(f"'## {top.name}': row for withdrawn criterion {cid}")
        else:
            problems.append(f"'## {top.name}': row for unknown criterion {cid}")
    return problems


def _marker_flags(tests_root: Path) -> tuple[dict[str, set[str]], list[tuple[CheckMarkers, str]]]:
    by_criterion: dict[str, set[str]] = {}
    all_markers: list[tuple[CheckMarkers, str]] = []
    for scan in scan_story_modules(tests_root):
        for check in scan.checks:
            for cid in check.ac:
                by_criterion.setdefault(cid, set()).update(check.planted_bugs)
            all_markers.extend((check, flag) for flag in check.planted_bugs)
    return by_criterion, all_markers


def check_planted_bugs(
    docs_root: Path,
    tests_root: Path,
    *,
    release: str | None | _FromEnvironment = FROM_ENV,
    registry: Sequence[str] | None = None,
    heal_vs_hide: Sequence[str] | None = None,
) -> list[str]:
    """Check 5: planted-bug consistency and completeness.

    ``registry`` and ``heal_vs_hide`` default to ``PLANTED_BUGS`` and the bug
    flags of preset ``drift_and_bug``, imported from the application lazily.
    """
    record = load_record(docs_root)
    if record is None or record.top is None:
        return []  # reported by check 4
    flags = tuple(registry) if registry is not None else registry_flags()
    heal = tuple(heal_vs_hide) if heal_vs_hide is not None else preset_bug_flags("drift_and_bug")
    known = set(flags)
    top = record.top
    where = f"'## {top.name}'"
    problems: list[str] = []

    record_flags: dict[str, set[str]] = {}
    for row in top.rows:
        record_flags.setdefault(row.criterion, set()).update(row.flags)
        for flag in row.flags:
            if flag not in known:
                problems.append(f"{where} {row.criterion}: unknown planted-bug flag {flag}; not in PLANTED_BUGS")

    markers, all_markers = _marker_flags(tests_root)
    for check, flag in all_markers:
        if flag not in known:
            problems.append(
                f"{check.module}::{check.name}: pytest.mark.planted_bug({flag!r}) names an unknown planted-bug flag {flag}"
            )
    for cid in sorted(set(record_flags) | set(markers), key=criterion_sort_key):
        in_record = record_flags.get(cid, set())
        on_checks = markers.get(cid, set())
        for flag in sorted(in_record - on_checks):
            problems.append(
                f"{cid}: the record lists {flag}, but no check of {cid} carries pytest.mark.planted_bug({flag!r})"
            )
        for flag in sorted(on_checks - in_record):
            problems.append(
                f"{cid}: a check carries pytest.mark.planted_bug({flag!r}), but the record row does not list {flag}"
            )

    flags_in_rows: dict[str, list[str]] = {}
    for row in top.rows:
        for flag in row.flags:
            flags_in_rows.setdefault(flag, []).append(row.criterion)
    no_criterion = Counter(entry.flag for entry in top.no_criterion)
    for entry in top.no_criterion:
        label = f"{where} '{NO_CRITERION_HEADING}' {entry.flag or '(empty flag)'} (line {entry.line})"
        if entry.flag not in known:
            problems.append(f"{label}: unknown planted-bug flag {entry.flag!r}; not in PLANTED_BUGS")
        if entry.flag in flags_in_rows:
            problems.append(
                f"{label}: {entry.flag} is also in the row(s) of {', '.join(flags_in_rows[entry.flag])}; never both"
            )
        if not entry.reason.strip():
            problems.append(f"{label}: no reason")
        elif not LINK_PATTERN.search(entry.reason):
            problems.append(f"{label}: the reason has no link to the approving PR")
    for flag, count in sorted(no_criterion.items()):
        if count > 1:
            problems.append(f"{where} '{NO_CRITERION_HEADING}': {flag} is listed {count} times")

    complete = release_tag(release) is not None or not any(row.status == PENDING for row in top.rows)
    if complete:
        planted = {flag for row in top.rows if row.status == PLANTED_BUG for flag in row.flags}
        for flag in flags:
            if flag not in planted and flag not in no_criterion:
                problems.append(
                    f"{flag}: registered planted bug in no planted-bug row of {where} and not under "
                    f"'{NO_CRITERION_HEADING}'"
                )
        for flag in heal:
            if flag not in planted:
                problems.append(f"{flag}: enabled by preset drift_and_bug but recorded on no planted-bug row of {where}")
            if flag in no_criterion:
                problems.append(
                    f"{flag}: enabled by preset drift_and_bug, so it must not be under '{NO_CRITERION_HEADING}'"
                )
    return problems


def check_index(docs_root: Path, tests_root: Path) -> list[str]:
    """Check 6: the index story table lists exactly the story files, with their counts."""
    index = load_index(docs_root)
    problems = list(index.problems)
    stories = {story.file_name: story for story in load_stories(docs_root)}
    listed: Counter[str] = Counter()
    for row in index.stories:
        label = f"{INDEX_FILE}:{row.line}: story row {row.id or '(empty ID)'}"
        listed[row.file] += 1
        if not STORY_ID_PATTERN.match(row.id):
            problems.append(f"{label}: {row.id!r} is not a story ID")
        story = stories.get(row.file)
        if story is None:
            problems.append(f"{label}: file {row.file!r} is not a story file in {docs_root.name}/")
            continue
        if story.id != row.id:
            problems.append(f"{label}: file {row.file} belongs to {story.id}")
        if row.active_criteria is None:
            problems.append(f"{label}: active criteria {row.raw_count!r} is not a number")
        elif row.active_criteria != len(story.numbers):
            problems.append(
                f"{label}: active criteria {row.active_criteria}, but {row.file} has {len(story.numbers)} "
                f"'### AC-<n>' headings"
            )
    for file_name, count in sorted(listed.items()):
        if count > 1:
            problems.append(f"{INDEX_FILE}: {file_name} has {count} rows in the story table")
    for file_name in sorted(stories):
        if listed[file_name] == 0:
            problems.append(f"{file_name}: story file missing from the index story table")
    return problems


def check_release(
    docs_root: Path, tests_root: Path, *, release: str | None | _FromEnvironment = FROM_ENV
) -> list[str]:
    """Check 7: in release mode the top section is the release tag and has no ``pending``."""
    tag = release_tag(release)
    if tag is None:
        return []
    record = load_record(docs_root)
    if record is None or record.top is None:
        return [f"release mode {RELEASE_ENV}={tag}: {RECORD_FILE} has no version section"]
    top = record.top
    problems: list[str] = []
    if top.name != tag:
        problems.append(
            f"release mode {RELEASE_ENV}={tag}: the top version section is '## {top.name}', expected '## {tag}'"
        )
    pending = [row.criterion for row in top.rows if row.status == PENDING]
    if pending:
        shown = ", ".join(pending[:5]) + (", ..." if len(pending) > 5 else "")
        problems.append(
            f"release mode {RELEASE_ENV}={tag}: '## {top.name}' still has {len(pending)} pending rows ({shown})"
        )
    return problems


def check_no_silent_removal(docs_root: Path, tests_root: Path) -> list[str]:
    """Check 8: released IDs stay active or withdrawn, and numbers have no gaps."""
    stories = load_stories(docs_root)
    index = load_index(docs_root)
    record = load_record(docs_root)
    active = _active_ids(stories)
    withdrawn = index.withdrawn_ids
    problems: list[str] = []

    if record is not None:
        reported: set[str] = set()
        for section in record.versions:
            if not section.released:
                continue
            for row in section.rows:
                cid = row.criterion
                if cid in active or cid in withdrawn or cid in reported:
                    continue
                reported.add(cid)
                problems.append(
                    f"{cid}: listed in the released section '## {section.name}' but neither an active heading "
                    f"in its story file nor in the withdrawn table (removed silently)"
                )

    numbers: dict[str, set[int]] = {story.id: set(story.numbers) for story in stories}
    for cid in withdrawn:
        parsed = parse_criterion_id(cid)
        if parsed:
            numbers.setdefault(parsed[0], set()).add(parsed[1])
    for story_id in sorted(numbers):
        present = numbers[story_id]
        if not present:
            continue
        for number in range(1, max(present) + 1):
            if number not in present:
                problems.append(
                    f"{criterion_id(story_id, number)}: gap in the criterion numbers of {story_id}; it is neither "
                    f"an active heading nor in the withdrawn table (removed silently)"
                )
    return problems


#: Statuses whose criterion may carry a ``## Revisions`` entry (besides withdrawn IDs).
REVISED_STATUSES: tuple[str, ...] = ("story-corrected", "planted-bug")
#: Tokens a story file never contains (design D1, D4 check 9), matched ignoring case.
FORBIDDEN_STORY_TOKENS: tuple[str, ...] = ("BUG_", "LOCATOR_", "planted", "drift", "CONFORMANCE.md", "backend/tests")
#: What a ``Replacement ID`` cell holds for a withdrawal without replacement.
NO_REPLACEMENT = frozenset({"", "-", "–", "—", "none", "n/a"})


def _revision_criterion(revision: Revision) -> str:
    return revision.criterion.strip().strip("`").strip()


def check_decision_records(docs_root: Path, tests_root: Path) -> list[str]:
    """Check 9: decision records are consistent, and story files stay neutral.

    * every ``story-corrected`` row (of any version section) has a
      ``## Revisions`` entry naming that criterion in its own story file;
    * every Revisions entry names a criterion of its story that is withdrawn or
      has status ``story-corrected`` or ``planted-bug`` in the top section;
    * every withdrawn ID's replacement is an active heading (or was itself
      withdrawn later, which its own withdrawn row then answers for);
    * no story file contains one of :data:`FORBIDDEN_STORY_TOKENS`, ignoring case.
    """
    stories = load_stories(docs_root)
    by_id = {story.id: story for story in stories}
    index = load_index(docs_root)
    record = load_record(docs_root)
    withdrawn = index.withdrawn_ids
    active = _active_ids(stories)
    problems: list[str] = []

    revised: dict[str, set[str]] = {
        story.id: {_revision_criterion(revision) for revision in story.revisions} for story in stories
    }

    if record is not None and record.top is not None:
        reported: set[str] = set()
        for section in record.versions:
            for row in section.rows:
                if row.status != "story-corrected" or row.criterion in reported:
                    continue
                parsed = parse_criterion_id(row.criterion)
                if parsed is None:
                    continue  # reported by check 4
                story = by_id.get(parsed[0])
                if story is None:
                    reported.add(row.criterion)
                    problems.append(
                        f"'## {section.name}' {row.criterion} (line {row.line}): story-corrected, but {parsed[0]} "
                        f"has no story file to hold its '## Revisions' entry"
                    )
                elif row.criterion not in revised[story.id]:
                    reported.add(row.criterion)
                    problems.append(
                        f"'## {section.name}' {row.criterion} (line {row.line}): story-corrected, but "
                        f"{story.file_name} has no '## Revisions' entry for {row.criterion}"
                    )

        top = record.top
        statuses = {row.criterion: row.status for row in top.rows}
        for story in stories:
            for revision in story.revisions:
                cid = _revision_criterion(revision)
                label = f"{story.file_name}:{revision.line}: '## Revisions' entry"
                parsed = parse_criterion_id(cid)
                if parsed is None:
                    problems.append(f"{label} names {cid!r}, which is not a criterion ID")
                    continue
                if parsed[0] != story.id:
                    problems.append(f"{label} for {cid}, a criterion of another story; it belongs in the {parsed[0]} file")
                    continue
                if cid in withdrawn:
                    continue
                status = statuses.get(cid)
                if status in REVISED_STATUSES:
                    continue
                found = f"status {status!r}" if status is not None else "no row"
                problems.append(
                    f"{label} for {cid}, but {cid} has {found} in '## {top.name}'; a Revisions entry needs a "
                    f"withdrawn criterion or status {' or '.join(REVISED_STATUSES)}"
                )

    for entry in index.withdrawn:
        replacement = entry.replacement.strip().strip("`").strip()
        if replacement.lower() in NO_REPLACEMENT:
            continue
        label = f"{INDEX_FILE}:{entry.line}: withdrawn {entry.id}"
        if parse_criterion_id(replacement) is None:
            problems.append(f"{label}: replacement {replacement!r} is not a criterion ID")
        elif replacement not in active and replacement not in withdrawn:
            problems.append(f"{label}: replacement {replacement} is not a '### AC-<n>' heading in its story file")

    for story in stories:
        revision_lines = {revision.line: _revision_criterion(revision) for revision in story.revisions}
        for number, text in enumerate(story.text.splitlines(), start=1):
            lowered = text.lower()
            for token in FORBIDDEN_STORY_TOKENS:
                if token.lower() not in lowered:
                    continue
                where = f" (Revisions entry for {revision_lines[number]})" if number in revision_lines else ""
                problems.append(
                    f"{story.file_name}:{number}{where}: mentions {token!r}; story files never name planted bugs, "
                    f"locators, drift, the conformance record or the tests"
                )
    return problems


#: The guard rules in D4 order.
GUARD_CHECKS: tuple[Callable[[Path, Path], list[str]], ...] = (
    check_headings,
    check_no_reuse,
    check_markers,
    check_record,
    check_planted_bugs,
    check_index,
    check_release,
    check_no_silent_removal,
    check_decision_records,
)


def run_guard(docs_root: Path, tests_root: Path) -> dict[str, list[str]]:
    """Every guard rule on one docs and tests tree: rule name -> problems."""
    return {check.__name__: check(docs_root, tests_root) for check in GUARD_CHECKS}


def all_active_ids(docs_root: Path) -> list[str]:
    """Every active criterion ID of the story set, sorted by story and number."""
    return sorted(_active_ids(load_stories(docs_root)), key=criterion_sort_key)


__all__ = [
    "FROM_ENV",
    "GUARD_CHECKS",
    "Criterion",
    "Index",
    "Record",
    "RecordLookupError",
    "RecordRow",
    "Story",
    "VersionSection",
    "all_active_ids",
    "check_decision_records",
    "check_headings",
    "check_index",
    "check_markers",
    "check_no_reuse",
    "check_no_silent_removal",
    "check_planted_bugs",
    "check_record",
    "check_release",
    "discover_story_files",
    "load_index",
    "load_record",
    "load_stories",
    "lookup",
    "parse_index",
    "parse_record",
    "parse_story",
    "run_guard",
    "scan_story_modules",
]
