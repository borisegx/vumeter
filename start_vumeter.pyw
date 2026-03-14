import sys
import os
from app import main

if __name__ == '__main__':
    # This explicit `.pyw` file tells the Python interpreter on Windows
    # to run the script using `pythonw.exe` instead of `python.exe`,
    # which automatically detaches and hides the black CMD window.
    
    # Ensure current directory is in path
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
