# Contributing to dxf-diff

Thanks for helping! Bug reports, test drawings, documentation fixes and pull
requests are all welcome.

## Reporting a bug

Please open an issue with:

- the dxf-diff version (`dxf-diff --version`), Python version and OS,
- the command you ran and what you expected,
- if possible a **small pair of DXF files** that shows the problem. Remove
  anything confidential first; often a few entities copied into a new drawing
  are enough.

## Development setup

```bash
git clone https://github.com/Shahnawaz75/dxf-diff
cd dxf-diff
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -e ".[test,png]"
pip install ruff
```

## Before you open a pull request

```bash
python -m pytest            # all tests must pass
ruff check .                # lint
ruff format .               # formatting (settings are in pyproject.toml)
```

- Add or update a test for every behavior change. Tests build their DXF files
  with ezdxf (see `tests/conftest.py`), so no binary fixtures are needed.
- Keep the package light: `ezdxf` is the only required dependency.
- Keep Python 3.9 compatibility (no `match` statements, no `X | Y` types at runtime).
- If you change the example or the report layout, regenerate the example files:

  ```bash
  python examples/make_tank_example.py
  dxf-diff examples/tank_rev_a.dxf examples/tank_rev_b.dxf --html examples/report.html
  ```

- Add a line to `CHANGELOG.md` under an "Unreleased" heading.

## Project layout

| Path | What it does |
| --- | --- |
| `src/dxf_diff/extract.py` | turns ezdxf entities into comparable property dicts |
| `src/dxf_diff/engine.py` | loads drawings, matches entities, layer and block comparison |
| `src/dxf_diff/describe.py` | short human-readable change descriptions |
| `src/dxf_diff/model.py` | result dataclasses and JSON serialization |
| `src/dxf_diff/render.py` | entity geometry as paths and text for the overlays |
| `src/dxf_diff/html_report.py` | self-contained HTML/SVG report |
| `src/dxf_diff/png_report.py` | optional matplotlib PNG |
| `src/dxf_diff/textconv.py` | normalized text dump for `git diff` |
| `src/dxf_diff/cli.py` | the `dxf-diff` command |

By contributing you agree that your contributions are licensed under the MIT license of this project.
