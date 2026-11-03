# Python Module Structure

## Limits

- A new module stays under 500 lines. A function over 60 lines is split before it grows further.
  Split a module that is already past 800 lines only when the owner asks.
- Find the module sizes with `git ls-files '*.py' | xargs wc -l | sort -rn | head`.
- One responsibility per module. The module docstring names it in one sentence. If the sentence
  needs "and" twice, the module should be two.

## Splitting a module

- Split into sibling modules named `<module>_<part>.py` in the same package, one responsibility each.
  A split is a move: bodies stay byte-identical, with no renames and no logic change in the same commit.
- The old `<module>.py` stays as a facade: its docstring, explicit imports of every name its callers
  use, and those names in `__all__`. New code imports from the module that defines the name.
- When a test patches `monkeypatch.setattr(<module>, "X", ...)`, the code under test must still read
  `<module>.X` at call time. If it no longer does, move the patch to the module that reads it, and
  show that the test still fails when the behaviour breaks.
- When two new modules reference each other only for a type, put that import under `if TYPE_CHECKING:`.
  Import each new module alone in a fresh interpreter to prove there is no cycle.
- Prove the move. Compare every top-level definition of the old file with the new files through
  `ast.dump`: all must be identical and none missing. Compare the sorted `uv run pytest --collect-only -q`
  output before and after: only paths may change.

## Splitting a test module

- Split `test_<module>.py` by behaviour into `test_<module>_<part>.py`, mirroring the source split.
- Put helpers that several test files share in a module under `tests/` that is not named
  `test_*.py`. Importing a fixture from another test file trips ruff F401/F811. Never widen
  `tests/conftest.py` for the fixtures of a single module.
