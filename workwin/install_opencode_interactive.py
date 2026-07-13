from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install SpecDiff OpenCode interactive artifacts into a target repository."
    )
    parser.add_argument("--target", required=True, help="Target code repository to audit interactively.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing SpecDiff-managed files. Other .opencode files are left untouched.",
    )
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"target path does not exist: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"target path is not a directory: {target}")

    opencode = target / ".opencode"
    opencode.mkdir(parents=True, exist_ok=True)

    copied = []
    skipped = []
    for source, dest in _install_plan(opencode):
        if source.is_dir():
            c, s = _copy_tree(source, dest, force=args.force)
            copied.extend(c)
            skipped.extend(s)
        else:
            if _copy_file(source, dest, force=args.force):
                copied.append(dest)
            else:
                skipped.append(dest)

    print(f"installed SpecDiff OpenCode artifacts into {opencode}")
    if copied:
        print(f"copied/updated {len(copied)} files")
    if skipped:
        print(f"skipped {len(skipped)} existing files; rerun with --force to update them")
    print("run from the target repo: opencode")
    print("then use: /spec-audit /path/to/requirements.json .specdiff/issues.json")
    return 0


def _install_plan(opencode: Path) -> Iterable[tuple[Path, Path]]:
    yield ROOT / ".opencode" / "commands", opencode / "commands"
    yield ROOT / ".opencode" / "agents", opencode / "agents"
    yield ROOT / ".opencode" / "tools", opencode / "tools"
    yield ROOT / "skills" / "spec-code-consistency", opencode / "skills" / "spec-code-consistency"
    yield ROOT / "specdiff", opencode / "specdiff-runtime" / "specdiff"
    yield ROOT / "specdiff-vendor-slim", opencode / "specdiff-runtime" / "specdiff-vendor-slim"


def _copy_tree(source: Path, dest: Path, *, force: bool) -> tuple[list[Path], list[Path]]:
    copied: list[Path] = []
    skipped: list[Path] = []
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        target = dest / rel
        if _copy_file(path, target, force=force):
            copied.append(target)
        else:
            skipped.append(target)
    return copied, skipped


def _copy_file(source: Path, dest: Path, *, force: bool) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        return False
    shutil.copy2(source, dest)
    return True


if __name__ == "__main__":
    raise SystemExit(main())
