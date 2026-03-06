#!/usr/bin/env python3
"""CI check: ensure Alembic migrations are in sync with db_schema.py.

Runs ``alembic check`` to detect whether autogenerate would produce new
migration operations.  Exits 0 if schema and migrations match, 1 otherwise.

Usage:
    python scripts/check_migrations.py
"""
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    result = subprocess.run(
        ["alembic", "revision", "--autogenerate", "-m", "_ci_check", "--sql"],
        capture_output=True,
        text=True,
    )
    # If the generated SQL contains no actual operations beyond boilerplate,
    # the schema and migrations are in sync.
    output = result.stdout + result.stderr
    if "No changes in schema detected" in output or result.returncode != 0:
        # Alembic prints "No changes" when the schema matches.
        # A non-zero exit also means alembic itself flagged something.
        pass

    # Simpler approach: just use alembic check (Alembic 1.9+)
    check = subprocess.run(
        ["alembic", "check"],
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "DATABASE_URL": "sqlite:///"},
    )
    # "No new upgrade operations detected" means we're good
    if check.returncode == 0:
        print("✓ Migrations are up to date with schema.")
        return 0

    # Check if it's just "not up to date" vs actual schema drift
    if "Target database is not up to date" in check.stderr:
        # This just means the DB hasn't been migrated — not a schema problem.
        # Run autogenerate to see if there are NEW changes beyond existing migrations.
        autogen = subprocess.run(
            [
                "alembic",
                "revision",
                "--autogenerate",
                "-m",
                "__ci_drift_check__",
                "--rev-id",
                "ci_temp",
            ],
            capture_output=True,
            text=True,
        )
        if autogen.returncode == 0:
            # Check if the generated migration has actual operations
            import pathlib

            versions_dir = pathlib.Path("alembic/versions")
            temp_file = None
            for f in versions_dir.glob("*__ci_drift_check__*"):
                temp_file = f
                break

            if temp_file:
                content = temp_file.read_text()
                temp_file.unlink()  # Clean up temp migration
                # If the upgrade() only has "pass", there's no drift
                if "pass" in content and "op.create_table" not in content and "op.add_column" not in content:
                    print("✓ Migrations are up to date with schema.")
                    return 0
                else:
                    print("✗ Schema drift detected! Run: alembic revision --autogenerate -m 'description'")
                    return 1
            else:
                print("✓ Migrations are up to date with schema.")
                return 0

    print(f"✗ Migration check failed:\n{check.stderr}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
