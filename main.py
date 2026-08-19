import os
import platform
import sys

# Add the project root to sys.path to ensure proper package imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if platform.system() != "Windows":
    print(f"Arrow Annotate requires Windows (detected {platform.system()}).\n"
          "Abilities using uiautomation, keyboard, and os.startfile are Windows-only.")
    sys.exit(1)

from arrow.app import main

if __name__ == "__main__":
    main()
