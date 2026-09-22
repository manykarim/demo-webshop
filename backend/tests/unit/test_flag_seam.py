"""Guard: the flag tables are queried only through the seam (task 5.4, design D4).

``core/feature_flags.py`` is the one flag API. If another application module
imports ``FeatureFlag`` or ``SpaceFeatureFlag`` it is about to read or write flag
rows behind the seam, which is how per-space values leak: a page that queries
the global table renders the ``default`` values in every space.

The check is static - every module under ``backend/app`` is parsed with ``ast``
- so it holds for code paths no test exercises, and it needs no application
import. The allowance list is deliberately short:

* ``core/feature_flags.py`` - the seam itself;
* ``core/db.py`` - registers the models with the metadata;
* ``models/`` - defines them;
* ``seeds/seed_data.py`` - inserts the seeded defaults.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

#: ``backend/app``: this file is ``backend/tests/unit/test_flag_seam.py``.
APP_ROOT = Path(__file__).resolve().parents[2] / "app"

#: The models that hold flag rows.
FLAG_MODEL_NAMES = frozenset({"FeatureFlag", "SpaceFeatureFlag"})

#: Modules allowed to import them, relative to :data:`APP_ROOT`.
ALLOWED_MODULES = frozenset({"core/feature_flags.py", "core/db.py", "seeds/seed_data.py"})

#: Package prefixes allowed to import them, relative to :data:`APP_ROOT`.
ALLOWED_PACKAGE_PREFIXES = ("models/",)


def app_modules() -> list[Path]:
    """Every Python module of the application, in a stable order."""
    return sorted(APP_ROOT.rglob("*.py"))


def module_name(path: Path) -> str:
    """``path`` as a POSIX path relative to ``backend/app``."""
    return path.relative_to(APP_ROOT).as_posix()


def is_allowed(name: str) -> bool:
    """Whether the module ``name`` may import the flag models."""
    return name in ALLOWED_MODULES or name.startswith(ALLOWED_PACKAGE_PREFIXES)


def imported_flag_models(path: Path) -> set[str]:
    """The flag model names that ``path`` imports, whatever the import form."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for alias in node.names:
            if alias.name.rsplit(".", 1)[-1] in FLAG_MODEL_NAMES:
                imported.add(alias.name.rsplit(".", 1)[-1])
    return imported


def test_the_guard_sees_the_application_modules() -> None:
    """A wrong ``APP_ROOT`` would make the guard below pass on nothing."""
    names = {module_name(path) for path in app_modules()}

    assert "main.py" in names
    assert "core/feature_flags.py" in names
    assert len(names) > 10


def test_the_seam_and_the_models_do_import_the_flag_models() -> None:
    """Control: the allowance list is not a list of modules that never import."""
    assert imported_flag_models(APP_ROOT / "core" / "feature_flags.py") == FLAG_MODEL_NAMES
    assert imported_flag_models(APP_ROOT / "seeds" / "seed_data.py") == {"FeatureFlag"}


@pytest.mark.parametrize("path", app_modules(), ids=module_name)
def test_flag_models_are_imported_only_through_the_seam(path: Path) -> None:
    """No module outside the seam, the models and the seeder imports them."""
    name = module_name(path)
    imported = imported_flag_models(path)

    if is_allowed(name):
        return

    assert not imported, (
        f"{name} imports {sorted(imported)} directly. Flags are read and written "
        "through backend/app/core/feature_flags.py (get_effective_flags, "
        "resolve_effective_flags, set_flags), so that every value is scoped to "
        "the workshop space of the request (design D4)."
    )
