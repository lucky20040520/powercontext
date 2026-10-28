# -*- coding: utf-8 -*-
"""
run_all.py —— 一键运行全部单元测试。

用法：python tests/run_all.py
说明：在 minimax/ 根目录下执行 python -m unittest discover -s tests 亦可。
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(
        os.path.dirname(os.path.abspath(__file__)), pattern="test_*.py"
    )
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
