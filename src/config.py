import json
import os


class DomainNotConfiguredError(Exception):
    pass


def get_domain_config(domain: str) -> dict:
    raw = os.environ.get("DOMAIN_CONFIG")
    if not raw:
        raise DomainNotConfiguredError(f"DOMAIN_CONFIG env var not set, cannot look up {domain}")

    try:
        config = json.loads(raw)
    except json.JSONDecodeError:
        raise DomainNotConfiguredError(f"DOMAIN_CONFIG is not valid JSON, cannot look up {domain}")

    if domain not in config:
        raise DomainNotConfiguredError(f"No config found for domain: {domain}")

    return config[domain]
