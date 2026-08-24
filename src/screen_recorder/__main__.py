"""Entry point for running the application with `python -m screen_recorder`.

Supports running directly from the source tree (without pip install) by
adding the ``src`` directory to ``sys.path`` when needed.
"""

import sys
from pathlib import Path

# Allow running from source tree: python -m screen_recorder from project root
_src = Path(__file__).resolve().parent.parent
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from screen_recorder.app import main

if __name__ == "__main__":
    main()
