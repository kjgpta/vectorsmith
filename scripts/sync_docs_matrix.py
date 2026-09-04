"""Synchronize the public backend capability matrix with canonical capabilities."""

from __future__ import annotations

import argparse
from pathlib import Path

from vectorsmith_core.adapters.capabilities import update_capability_matrix_document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--document",
        type=Path,
        default=Path("docs/vector-stores.md"),
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    original = args.document.read_text(encoding="utf-8")
    updated = update_capability_matrix_document(original)
    if args.check:
        return int(original != updated)
    args.document.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
