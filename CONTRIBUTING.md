# Contributing

Thanks for taking a look. This repository is small on purpose: the value is in
the workflow being clear enough that someone can adopt it without asking
questions.

## Before you open a pull request

1. Run the test suite:

   ```bash
   python -m unittest discover -s tests -v
   ```

2. If you changed the installer behavior, add or update a test that would fail
   without your change.
3. If you changed the workflow, update `ARCHITECTURE.md` and `skill/SKILL.md`
   together, plus the matching reference under `skill/references/`. The
   explanation and the operational instructions must not drift apart.
4. If you changed hook behavior, describe the exact hook event, input, and
   output you relied on. Cite the release documentation rather than a
   development branch of the schemas.

## What tends to get accepted

- Fixes that keep the safety properties in [SECURITY.md](SECURITY.md): no silent
  overwrites, no secret handling, no network use in the installer, hooks that
  fail open.
- Documentation that removes a real ambiguity a reader would hit.
- Portability fixes for Windows, macOS, and Linux that stay inside the Python
  standard library.
- Test coverage for behavior that could plausibly regress.

## What tends to get pushed back

- Making the installer write into a guessed Codex home.
- Adding a bundled dependency, especially a non-stdlib one, without a strong
  reason.
- Making a hook able to block a user's turn on a hook bug.
- Adding workflow features that exist only to add parallelism. The workflow is
  deliberately one root, one worker, one review.

## Style

- Python: standard library only, type hints where they help, no f-strings with
  side effects in log paths, and comments only where the intent is not obvious.
- Markdown: short sections, tables where they genuinely compress information,
  and no unexplained jargon.
- ASCII by default. `README_RU.md` is the one documented non-ASCII file.

## Reporting issues

Include the output of:

```bash
python scripts/verify_install.py --project /path/to/project --codex-home /path/to/.codex --self-test
```

and your operating system plus Python version. Do not include real router
capability URLs, API keys, or private repository paths.

## License

By contributing, you agree that your contributions are licensed under the MIT
License in [LICENSE](LICENSE).
