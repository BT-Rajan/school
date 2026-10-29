"""Seed for the Phase 4 browser test (e2e/phase4.cjs): the Phase 3 seed as it is.

Noura is assigned to both schools and the MOE-SV-02 form is open, so she can start an
evaluation and scan a report while offline. Yousef, the second supervisor, has no schools,
so his open screens must receive no event about her work. Never run it against production.

Usage, from backend/ with the app's environment set and migrations applied:
  PYTHONPATH=.:../e2e .venv/bin/python ../e2e/seed_phase4.py > seed.json
"""

import json

from seed_phase3 import seed3


def main() -> None:
    print(json.dumps(seed3()))


if __name__ == "__main__":
    main()
