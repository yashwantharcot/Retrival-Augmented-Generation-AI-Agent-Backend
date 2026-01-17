import os, sys
# Ensure repository root is on sys.path for 'app' imports in tests
ROOT = os.path.abspath(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
