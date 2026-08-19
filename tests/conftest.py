"""Shared fixtures for the load_profile test suite."""

from __future__ import annotations

import copy

import pytest

from load_profile.config import load_config


@pytest.fixture(scope="session")
def base_cfg():
    """Load the real project config once per session."""
    return load_config()


@pytest.fixture
def cfg(base_cfg):
    """A fresh deep copy of the config for each test, safe to mutate."""
    return copy.deepcopy(base_cfg)
