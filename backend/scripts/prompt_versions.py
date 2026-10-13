"""List prompt versions, lint them, and manage the lock file (A26).

    python scripts/prompt_versions.py            # table + lint
    python scripts/prompt_versions.py --check    # exit 1 if lint fails or a prompt changed without a new version
    python scripts/prompt_versions.py --update   # re-lock after an intentional edit of an UNSCORED prompt
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.prompts import registry as R  # noqa: E402


def main(argv: list[str]) -> int:
    if "--update" in argv:
        bad = R.lint_all()
        if bad:
            print("Fix these first:\n  " + "\n  ".join(bad))
            return 1
        R.write_lock()
        print(f"Locked {len(R.prompt_names())} prompts -> {R.LOCK_PATH.name}")
        return 0
    print(f"{'prompt':<22}{'ver':>4}{'temp':>6}  {'hash':<13}used by")
    for i in R.describe():
        used = ", ".join(i.used_by) or ("(planned)" if i.label in R.PLANNED_UNUSED else "NOT USED")
        print(f"{i.label:<22}{i.version:>4}{i.temperature:>6}  {i.fingerprint:<13}{used}")
    problems = R.lint_all() + R.lock_problems()
    for p in problems:
        print("PROBLEM:", p)
    if not problems:
        print("OK: all prompts lint clean and match the lock file.")
    return 1 if problems and "--check" in argv else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
