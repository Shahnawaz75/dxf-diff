"""Allow ``python -m dxf_diff OLD NEW``."""

import sys

from .cli import main

sys.exit(main())
