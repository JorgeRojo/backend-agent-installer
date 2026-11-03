# Python Style

The conventions of the Red Points Python services (from the hefesto repos). The repo's ruff
configuration is the lint gate: run `uv run --no-sync ruff check` and `uv run --no-sync ruff format --check`.
Everything below is checked by review, not by ruff.

- Python 3.11+. Every module starts with a docstring. Every module holding code follows it with
  `from __future__ import annotations`.
- Type hints on every signature, public and private. `Any` only at the boundary of an untyped payload.
- Functions with more than two parameters, or with two of the same type, take keyword-only
  arguments (`*,`).
- `@dataclass(frozen=True)` for values. Use plain `@dataclass` only for state that is mutated.
  Collection fields use `field(default_factory=...)`. No mutable default arguments.
- Pydantic models for what crosses a boundary: an HTTP or tool contract, a message, a config file.
- Constants are module-level `UPPER_CASE`, with a `#:` comment when the name does not give the unit.
- Text a model reads (prompts, rubrics, templates) lives in files the code loads, never in string
  literals inside logic.
- Exceptions: never a bare `except:`. Catch the narrowest type. `except Exception` carries
  `# noqa: BLE001 - <what the catch protects>` and ends in a declared outcome, never in silence.
- Logging: structured, an event name plus keyword fields, never an f-string:
  `log.info("service.step.done", items=count)`. Where `redpoints_agent_base` is a dependency, use
  `get_logger(__name__)` from `redpoints_agent_base.logging`. Log `type(exc).__name__` rather than
  the exception text when that text can carry user content or a token.
- No `print` in library or service code. Never log or write a token, a password or an AWS
  credential.
