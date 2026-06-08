"""Unit tests for the config loader (DESIGN.md Step 3).

These tests exercise:
- Default loading (finds config.example.yaml in CWD)
- Explicit path and TINYLLM_CONFIG env
- ${VAR} / $VAR recursive expansion
- api_key_env resolution (env wins)
- Minimal validation (base_url required)
- log_level (logging.level + top-level compat)
- Resulting Config dataclass shape and helper methods

All tests are pure and do not affect global state except via monkeypatch.
"""

from pathlib import Path

import pytest
import yaml

from tiny_llm_proxy.config import load_config


def test_load_default_finds_example():
    """When no config.yaml, load_config() falls back to config.example.yaml."""
    cfg = load_config()
    assert cfg.default_provider == "lmstudio"
    assert "lmstudio" in cfg.providers
    assert "openrouter" in cfg.providers
    assert cfg.providers["lmstudio"]["base_url"].startswith("http://localhost:1234")
    # lmstudio should have resolved api_key = None (null or empty in yaml)
    assert cfg.providers["lmstudio"]["api_key"] is None
    assert cfg.config_path is not None
    assert "config.example.yaml" in (cfg.config_path or "")


def test_load_explicit_path(tmp_path: Path):
    """Explicit --config path is respected (and must exist)."""
    cfg_file = tmp_path / "myconfig.yaml"
    cfg_file.write_text(
        yaml.safe_dump(
            {
                "default_provider": "openrouter",
                "providers": {
                    "openrouter": {
                        "base_url": "https://example.com/v1",
                        "api_key": "sk-test-literal",
                    }
                },
            }
        )
    )
    cfg = load_config(str(cfg_file))
    assert cfg.default_provider == "openrouter"
    assert cfg.providers["openrouter"]["api_key"] == "sk-test-literal"
    assert cfg.config_path == str(cfg_file.resolve())


def test_load_via_env(monkeypatch, tmp_path: Path):
    """TINYLLM_CONFIG env var is used when no explicit arg."""
    cfg_file = tmp_path / "envconfig.yaml"
    cfg_file.write_text(
        yaml.safe_dump({"default_provider": "lmstudio", "log_dir": "/tmp/custom-logs"})
    )
    monkeypatch.setenv("TINYLLM_CONFIG", str(cfg_file))
    cfg = load_config()  # no arg -> should read env
    assert cfg.log_dir == "/tmp/custom-logs"


def test_env_var_expansion(monkeypatch, tmp_path: Path):
    """${VAR} and $VAR are expanded recursively in the loaded structure."""
    monkeypatch.setenv("TEST_BASE", "http://127.0.0.1:9999")
    monkeypatch.setenv("TEST_SUFFIX", "/v1")
    cfg_file = tmp_path / "expand.yaml"
    cfg_file.write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "test": {
                        "base_url": "${TEST_BASE}${TEST_SUFFIX}",
                        "extra_headers": {"X-Foo": "bar-$TEST_SUFFIX"},
                    }
                }
            }
        )
    )
    cfg = load_config(str(cfg_file))
    p = cfg.providers["test"]
    assert p["base_url"] == "http://127.0.0.1:9999/v1"
    assert p["extra_headers"]["X-Foo"] == "bar-/v1"


def test_api_key_env_resolution_wins(monkeypatch, tmp_path: Path):
    """api_key_env takes precedence over literal api_key in the yaml."""
    monkeypatch.setenv("MY_KEY", "sk-from-env-12345")
    cfg_file = tmp_path / "keyenv.yaml"
    cfg_file.write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "cloud": {
                        "base_url": "https://cloud.example/v1",
                        "api_key": "sk-literal-should-be-ignored",
                        "api_key_env": "MY_KEY",
                    },
                    "local": {
                        "base_url": "http://localhost:1234/v1",
                        "api_key": None,
                    },
                }
            }
        )
    )
    cfg = load_config(str(cfg_file))
    assert cfg.providers["cloud"]["api_key"] == "sk-from-env-12345"
    assert cfg.providers["local"]["api_key"] is None


def test_missing_base_url_raises(tmp_path: Path):
    """Provider without base_url fails fast (validation per DESIGN.md)."""
    cfg_file = tmp_path / "bad.yaml"
    cfg_file.write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "broken": {
                        "api_key": "foo",
                        # no base_url
                    }
                }
            }
        )
    )
    with pytest.raises(ValueError, match="base_url"):
        load_config(str(cfg_file))


def test_explicit_missing_file_raises():
    """Explicit path that does not exist -> clear error (fail fast)."""
    with pytest.raises(FileNotFoundError, match="not found"):
        load_config("/this/path/does/not/exist/anywhere.yaml")


def test_log_level_from_logging_section_and_compat(tmp_path: Path):
    """log_level comes from logging.level; top-level log_level is accepted for compat."""
    cfg_file = tmp_path / "loglevel.yaml"
    cfg_file.write_text(yaml.safe_dump({"logging": {"level": "DEBUG"}}))
    cfg = load_config(str(cfg_file))
    assert cfg.log_level == "debug"

    cfg_file2 = tmp_path / "loglevel2.yaml"
    cfg_file2.write_text(yaml.safe_dump({"log_level": "warning"}))
    cfg2 = load_config(str(cfg_file2))
    assert cfg2.log_level == "warning"


def test_config_get_provider_and_shape():
    """Config object shape and helpers match what later steps (routing, forward) expect."""
    cfg = load_config()  # uses example
    p = cfg.get_provider("lmstudio")
    assert "base_url" in p
    assert "api_key" in p

    with pytest.raises(KeyError):
        cfg.get_provider("nonexistent")

    # routing rules are present
    assert "prefix_map" in cfg.routing
    assert isinstance(cfg.routing["header_names"], list)


def test_defaults_when_no_files(monkeypatch, tmp_path: Path):
    """If no config files at all, we still get usable defaults (for tests/CI)."""
    # Force a temp cwd with nothing
    monkeypatch.chdir(tmp_path)
    # Also clear any TINYLLM_CONFIG
    monkeypatch.delenv("TINYLLM_CONFIG", raising=False)

    cfg = load_config()
    assert cfg.default_provider == "lmstudio"
    assert "lmstudio" in cfg.providers
    assert cfg.providers["lmstudio"]["base_url"]
