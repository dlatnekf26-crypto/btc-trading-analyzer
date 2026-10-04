"""Untrusted settings JSON must produce validation errors, not runtime exceptions."""

import pytest
from btc_analyzer.config import AppConfig


@pytest.mark.parametrize("data", [[], None, "settings", 12])
def test_config_root_requires_object(data):
    with pytest.raises(ValueError, match="JSON object"):
        AppConfig.from_dict(data)


@pytest.mark.parametrize("section", ["indicators", "strategy", "risk"])
@pytest.mark.parametrize("value", [None, [], "invalid"])
def test_config_sections_require_objects(section, value):
    with pytest.raises(ValueError, match=section):
        AppConfig.from_dict({section: value})


def test_typo_does_not_silently_use_defaults():
    with pytest.raises(ValueError, match="riks"):
        AppConfig.from_dict({"riks": {"capital": 50000}})


def test_nested_type_error_is_validation_error():
    with pytest.raises(ValueError, match="risk"):
        AppConfig.from_dict({"risk": {"capital": "not a number"}})


def test_valid_config_roundtrip():
    config = AppConfig.from_dict(AppConfig().to_dict())
    assert config.to_dict() == AppConfig().to_dict()
