import sys
import os

# Add project root to path
# We need to add the directory containing 'app' to sys.path
# 'entry.py' is in 'app/desktop/entry.py'
# so 'app' is in '../../' relative to 'entry.py'

current_dir = os.path.dirname(os.path.abspath(__file__))
# current_dir is .../app/desktop
project_root = os.path.abspath(os.path.join(current_dir, "../.."))
# project_root is .../Sage

if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Now we can import app.desktop.core.main
# This ensures that relative imports inside app.desktop.core work correctly
from app.desktop.core.main import main

if __name__ == "__main__":
    sys.exit(main())
