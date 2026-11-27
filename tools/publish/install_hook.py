"""Install the FLUX pre-push hook in this clone (shared by all its worktrees).

The hook runs tools/publish/pre_push.py, then the workspace guard (`tools/ws.py guard pre-push`)
when a workspace holding the repo provides one, then Git LFS when the repo uses it.
An existing hook that is not ours is kept as pre-push.bak.

Usage: python tools/publish/install_hook.py [--ws-py <path to ws.py>]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import checks  # noqa: E402

MARKER = "# flux-publish-hook"

HOOK = """#!/bin/sh
{marker}: written by tools/publish/install_hook.py, rerun it to update
INPUT=$(cat)
ROOT="$(git rev-parse --show-toplevel)"
HOOK_PY="$ROOT/tools/publish/pre_push.py"
[ -f "$HOOK_PY" ] || HOOK_PY="{fallback}"
if command -v python >/dev/null 2>&1; then PYTHON="python"
elif command -v py >/dev/null 2>&1; then PYTHON="py -3"
else echo "flux hook: no Python found, push refused" >&2; exit 1
fi
if [ ! -f "$HOOK_PY" ]; then echo "flux hook: pre_push.py not found, push refused" >&2; exit 1; fi
printf '%s\\n' "$INPUT" | $PYTHON "$HOOK_PY" "$@" || exit 1

WS_PY="{ws_py}"
if [ -n "$WS_PY" ] && [ -f "$WS_PY" ]; then
  printf '%s\\n' "$INPUT" | $PYTHON "$WS_PY" guard pre-push --repo "$ROOT" || exit 1
fi

if git rev-parse --git-path lfs >/dev/null 2>&1 && grep -qs "filter=lfs" "$ROOT/.gitattributes"; then
  if ! command -v git-lfs >/dev/null 2>&1; then echo "flux hook: git-lfs is not installed" >&2; exit 2; fi
  printf '%s\\n' "$INPUT" | git lfs pre-push "$@" || exit $?
fi
exit 0
"""


def find_ws_py(main_checkout: Path) -> Path | None:
    for parent in main_checkout.parents:
        candidate = parent / "tools" / "ws.py"
        if candidate.is_file():
            return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the FLUX pre-push hook.")
    parser.add_argument("--ws-py", type=Path, default=None)
    args = parser.parse_args(argv)

    repo = checks.repo_root(Path(__file__).resolve().parent)
    common = Path(checks.git_text(["rev-parse", "--git-common-dir"], repo))
    if not common.is_absolute():
        common = (repo / common).resolve()
    main_checkout = common.parent
    ws_py = args.ws_py or find_ws_py(main_checkout)
    hooks = common / "hooks"
    hooks.mkdir(exist_ok=True)
    target = hooks / "pre-push"
    if target.is_file() and MARKER not in target.read_text(encoding="utf-8", errors="replace"):
        backup = hooks / "pre-push.bak"
        backup.write_bytes(target.read_bytes())
        print(f"previous hook kept as {backup}")
    fallback = (main_checkout / "tools" / "publish" / "pre_push.py").as_posix()
    text = HOOK.format(marker=MARKER, fallback=fallback, ws_py=ws_py.as_posix() if ws_py else "")
    target.write_bytes(text.encode("utf-8"))
    print(f"hook written: {target}")
    print(f"workspace guard: {ws_py if ws_py else 'none found, skipped'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
