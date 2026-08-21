#!/usr/bin/env python3
"""Render templates/cronjob.yaml.j2 for every combination lrcm can produce.

The template is Jinja2, so ansible-lint cannot parse it directly. CI renders it
with this helper first and then lints the result, which is what actually gets
handed to ansible-runner on a client.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lrcm import CRONJOB_SPECIAL_TIMES, render_cronjob_playbook  # noqa: E402


def main() -> int:
    """Render every cron playbook variant into the requested directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path)
    arguments = parser.parse_args()

    out_dir: Path = arguments.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    for special_time in CRONJOB_SPECIAL_TIMES:
        for enabled in (True, False):
            suffix = "present" if enabled else "absent"
            output_path = out_dir / f"cronjob_{special_time}_{suffix}.yaml"
            render_cronjob_playbook(
                template_directory=REPO_ROOT / "templates",
                output_path=output_path,
                special_time=special_time,
                job="/opt/lrcm/lrcm.py --configfile=/etc/lrcm/lrcm.conf",
                enabled=enabled,
            )
            print(f"rendered {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
