"""Entry point:  python -m courier_outreach <command>

Commands: run | source | send | read | sync | init-db | serve
"""

import sys

from .orchestrator import main

if __name__ == "__main__":
    sys.exit(main())
