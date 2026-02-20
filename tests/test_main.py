"""Basic tests for rumi."""

import pytest


def test_import():
    """Test that rumi can be imported."""
    import rumi

    assert rumi.__version__ == "0.1.0"
