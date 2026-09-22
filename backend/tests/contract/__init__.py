"""The contract test suite for locator drift (drift-coverage Decision 7).

A package, so its modules can import one another (``semantic``, ``hooks``,
``coverage_oracle`` and ``structure_oracle``) and so that pytest imports the
test modules under stable dotted names.

The suite renders every covered page in stages 1 to 4 and checks two things
against the stage-1 render of the same build:

* the **semantic snapshot** is identical (``semantic.py``) - what a user and an
  assistive technology perceive never changes with the stage;
* the **hooks** changed exactly as the mapping in ``backend/app/core/workshop``
  declares (``hooks.py``), the stage-1 selectors a participant would have
  written break in exactly the stages that must break them
  (``coverage_oracle.py``), and stage 4 really re-nests the components it
  declares (``structure_oracle.py``).

Nothing in this package imports ``backend.app`` at module level; the fixtures of
``conftest.py`` do that inside their bodies, exactly like the root conftest.
"""
