#!/usr/bin/env python
"""Repository-root entry point for the Django project kept under starter/."""
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
STARTER_ROOT = PROJECT_ROOT / "starter"
sys.path.insert(0, str(STARTER_ROOT))


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dealerdesk.settings")
    if len(sys.argv) == 2 and sys.argv[1] == "test":
        sys.argv.append("core.tests")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()