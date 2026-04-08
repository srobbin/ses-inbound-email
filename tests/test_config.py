import json
import os
import pytest
from src.config import get_domain_config, DomainNotConfiguredError


class TestGetDomainConfig:
    def test_returns_config_for_known_domain(self, domain_config, monkeypatch):
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))

        result = get_domain_config("letterclub.org")

        assert result["webhook_url"] == "https://letterclub.org/webhooks/inbound"
        assert result["signing_secret"] == "test-secret-key"

    def test_returns_config_for_different_domain(self, domain_config, monkeypatch):
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))

        result = get_domain_config("other-app.com")

        assert result["webhook_url"] == "https://other-app.com/webhooks/inbound"

    def test_raises_for_unknown_domain(self, domain_config, monkeypatch):
        monkeypatch.setenv("DOMAIN_CONFIG", json.dumps(domain_config))

        with pytest.raises(DomainNotConfiguredError, match="unknown.com"):
            get_domain_config("unknown.com")

    def test_raises_when_env_var_missing(self, monkeypatch):
        monkeypatch.delenv("DOMAIN_CONFIG", raising=False)

        with pytest.raises(DomainNotConfiguredError):
            get_domain_config("letterclub.org")

    def test_raises_when_env_var_is_invalid_json(self, monkeypatch):
        monkeypatch.setenv("DOMAIN_CONFIG", "not-json")

        with pytest.raises(DomainNotConfiguredError):
            get_domain_config("letterclub.org")
