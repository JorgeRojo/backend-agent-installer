# Python Tests

- Layout: flat `tests/test_<module>.py`, using pytest functions and fixtures. Add a test class only
  when the file already uses classes. Write test data and assertion messages in English.
- Unit tests make no network and no AWS calls. Use the doubles and recorded fixtures the repo already
  has before you write a new one, and give a fixture only the shapes the real dependency produces.
- When a change rewrites a golden or snapshot file, read the diff of every rewritten file before
  you keep it.
- A test must be able to fail:
  - Never compute a boundary input from the constant under test. Use literals you have checked, add
    a control case on the other side of the boundary, and pin the constant in a test of its own.
  - When two branches end in the same state, make each one observable, usually with a partial success.
  - Assert exact sets of identifiers, not counts.
- Mutation-verify every test you call load-bearing: apply the mutation it should catch, show that it
  fails, revert the mutation, and report both runs.
- A suite that runs on fixtures proves nothing about a live model or service obeying a prompt or a
  contract. That needs a live run, and a live run needs the owner's approval.

## Picking the tests to run

While you work, run the tests the change affects. Depth 2 is enough; depth 5 selects the whole suite:

```bash
git diff --name-only HEAD | npx -y @colbymchenry/codegraph@1.6.2 affected --stdin --quiet -d 2 \
  --filter 'tests/test_*.py' | xargs -r uv run --no-sync pytest
```

If the checkout has no `.codegraph/`, run the full suite instead. The repo's full gates still run at
the end.
