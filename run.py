"""Launch Charly6 from the project root without activating the venv."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from charly6.app import main

main()
