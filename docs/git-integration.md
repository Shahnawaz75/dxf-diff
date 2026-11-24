---
title: Diff DXF files in git with dxf-diff
description: Make git diff, git log -p and pull request reviews readable for DXF drawings with dxf-diff --textconv, and open a visual DXF diff with git difftool.
---

# Diff DXF files in git

Git stores DXF files fine, but `git diff` on a DXF drawing shows thousands of group codes, handles and timestamps. dxf-diff offers two ways to make drawing changes reviewable:

1. **textconv**: `git diff` shows a readable, sorted text version of each drawing.
2. **difftool**: `git difftool` runs a full dxf-diff comparison and opens the visual HTML report.

## 1. Readable `git diff` with textconv

`dxf-diff --textconv FILE` prints a normalized dump of a drawing:

- one record per entity (`TYPE layer=... property=value ...`), vertices one per line,
- handles, GUIDs and timestamps are left out,
- layers, block definitions and the entities of each layout are sorted,
- numbers are rounded to 6 decimals, the output is UTF-8 with LF line endings on every OS.

So saving a drawing again without changes gives the same text, and an edit shows up as a small diff.

Setup, once per machine (use `git config` without `--global` to set it for one repository only):

```bash
git config --global diff.dxf.textconv "dxf-diff --textconv"
git config --global diff.dxf.cachetextconv true   # optional: cache the text per file version
```

Then tell git which files use it, in the repository's `.gitattributes`:

```gitattributes
*.dxf diff=dxf
*.DXF diff=dxf
```

Commit the `.gitattributes` file so everybody gets the same behavior (each person still needs the `git config` line and dxf-diff on their `PATH`). Now `git diff`, `git log -p`, `git show` and `git diff --cached` show changes like this:

```diff
@@ -38,10 +39,10 @@ LAYOUT "Model"
-  DIMENSION layer="DIMENSIONS" measurement=3000 text_override="<>" dimtype=0 defpoint=(6010,0) defpoint2=(4000,0) defpoint3=(4230,3000) dimstyle="GA"
+  DIMENSION layer="DIMENSIONS" measurement=3600 text_override="<>" dimtype=0 defpoint=(6010,0) defpoint2=(4000,0) defpoint3=(4230,3600) dimstyle="GA"
-  INSERT layer="NOZZLES" name="TANK-NOZZLE" insert=(4000,1800) xscale=1 yscale=1 zscale=1 rotation=0 attribs={RATING="150#", SIZE="4\"", TAG="N2"}
+  INSERT layer="NOZZLES" name="TANK-NOZZLE" insert=(4000,1800) xscale=1 yscale=1 zscale=1 rotation=0 attribs={RATING="150#", SIZE="6\"", TAG="N2"}
```

To see the raw DXF text again, use `git diff --no-textconv`.

Notes:

- Textconv affects only how diffs are displayed; the files in the repository are unchanged.
- On Windows, if git cannot find `dxf-diff`, use the full path of the executable, for example `git config --global diff.dxf.textconv "C:/path/to/venv/Scripts/dxf-diff.exe --textconv"`.
- Because records are sorted, an entity that changes a lot may move to another place in the dump; the diff then shows it as one line removed and one added.

## 2. Visual diff with `git difftool`

```bash
git config --global difftool.dxf-diff.cmd 'dxf-diff "$LOCAL" "$REMOTE" --open'
git difftool -y -t dxf-diff HEAD~1 -- drawings/plan.dxf
```

`--open` writes the HTML report to a temporary file and opens it in your browser. Use `--html some/path.html` to keep the report, or replace `--open` with nothing to just print the summary in the terminal.

## 3. In pull requests and CI

Run dxf-diff in CI on the drawings a pull request changes and upload the HTML reports as build artifacts. The exit status is `0` (no differences), `1` (differences) or `2` (error). The job needs the history of `main` (for GitHub Actions: `actions/checkout` with `fetch-depth: 0`):

```bash
mkdir -p reports
for f in $(git diff --name-only origin/main...HEAD -- '*.dxf'); do
  git show "origin/main:$f" > /tmp/base.dxf 2>/dev/null || continue   # new file: nothing to compare
  dxf-diff /tmp/base.dxf "$f" --html "reports/$(basename "$f" .dxf).html" || test $? -eq 1
done
```

See the "Use in CI" section of the [README](https://github.com/Shahnawaz75/dxf-diff#use-in-ci) for a complete GitHub Actions example.
