import os
import sys

if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    CODE_ROOT = sys._MEIPASS
    ROOT_DIR = os.path.dirname(sys.executable)
else:
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(_script_dir) == "src":
        CODE_ROOT = os.path.dirname(_script_dir)
    else:
        CODE_ROOT = _script_dir
    ROOT_DIR = os.path.dirname(CODE_ROOT)
