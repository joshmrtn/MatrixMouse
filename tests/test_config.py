"""
tests/test_config.py

Tests for matrixmouse.config
"""

from matrixmouse.config import MatrixMouseConfig

def test_clarification_grace_period_default():
    cfg = MatrixMouseConfig()
    assert cfg.clarification_grace_period_minutes == 10