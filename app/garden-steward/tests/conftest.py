import os
import sys

# Let the tests import the app modules (python/config.py, python/brain.py, ...).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
