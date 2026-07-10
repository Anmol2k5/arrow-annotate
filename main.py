import sys
import os

# Add the project root to sys.path to ensure proper package imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arrow.app import main

if __name__ == "__main__":
    main()
