#!/usr/bin/env bash
# Add in-place checkpoint/rollback to melee-sim-light (patches/melee-sim-light-checkpoint.patch), build it and put
# the library into the venv. Needed by melee_llm/sim/rollback.py; `uv sync --reinstall` undoes it, so run this again.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC=vendor/melee-sim-light
REV=$(sed -n 's/.*melee-sim-light".*rev = "\([0-9a-f]*\)".*/\1/p' pyproject.toml)
[ -d "$SRC/.git" ] || git clone -q https://github.com/kyhavlov/melee-sim-light "$SRC"
git -C "$SRC" diff --quiet || { git -C "$SRC" apply --reverse --check "$PWD/patches/melee-sim-light-checkpoint.patch" 2>/dev/null \
  && echo "patch already applied" || { echo "$SRC has other local changes; not touching it" >&2; exit 1; }; }
if git -C "$SRC" diff --quiet; then
  git -C "$SRC" checkout -q "$REV"
  git -C "$SRC" apply "$PWD/patches/melee-sim-light-checkpoint.patch"
fi
# upstream's install builds `python-library`, which is unoptimised; `python-release` is its exactness-audited
# optimised profile: the same play frame for frame (checked over 60,000 frames) and about 1.5 times faster
make -C "$SRC" --no-print-directory python-release PY="$PWD/.venv/bin/python" -j"$(nproc)"
DEST=$(.venv/bin/python -c "import melee_sim, pathlib; print(pathlib.Path(melee_sim.__file__).parent)")
cp "$SRC/build/melee_core/python-release/libmelee_core.so" "$DEST/libmelee_core.so.new"
strip -S "$DEST/libmelee_core.so.new"
mv "$DEST/libmelee_core.so.new" "$DEST/libmelee_core.so"   # a rename, so processes using the old file keep it
echo "patched library installed in $DEST"
