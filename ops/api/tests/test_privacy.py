"""Test privacy utilities."""
import pytest
from resolvix_ops.privacy import mask_number


def test_mask_number_full():
    """Test masking a full E.164 number."""
    assert mask_number("+919876540002") == "+91•••••0002"
    assert mask_number("+12025551234") == "+12•••••1234"


def test_mask_number_short():
    """Test masking a short number (< 8 chars)."""
    assert mask_number("1234567") == "•••"
    assert mask_number("123") == "•••"
    assert mask_number("") == "•••"


def test_mask_number_none():
    """Test masking None."""
    assert mask_number(None) is None


def test_mask_number_exactly_8_chars():
    """Test masking an 8-character number."""
    assert mask_number("12345678") == "123•••••5678"
