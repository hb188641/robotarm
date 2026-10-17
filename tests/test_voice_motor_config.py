import json
import pytest
from TITI.voice_motor import config


def test_env_precedence_and_missing_explicit_file(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(config, "ROOT", root)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=parent-test-value\n")
    assert config.load_api_key() == "parent-test-value"
    (root / ".env").write_text("OPENAI_API_KEY=root-test-value\n")
    assert config.load_api_key() == "root-test-value"
    custom = tmp_path / "custom.env"
    custom.write_text("OPENAI_API_KEY=custom-test-value\n")
    assert config.load_api_key(custom) == "custom-test-value"
    monkeypatch.setenv("OPENAI_API_KEY", "process-test-value")
    assert config.load_api_key(custom) == "process-test-value"
    with pytest.raises(ValueError):
        config.load_api_key(tmp_path / "absent.env")


def test_no_key_reports_name_without_values(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(config, "ROOT", root)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        config.load_api_key()


def test_limits_require_every_joint_and_strict_numbers(tmp_path):
    p = tmp_path / "limits.json"
    valid = {
        f"motor_{i}": {"min": 100, "max": 3000, "max_delta": 200} for i in range(1, 7)
    }
    p.write_text(json.dumps(valid))
    assert config.load_limits(p)["motor_3"]["max_delta"] == 200
    for broken in [
        dict(list(valid.items())[1:]),
        {**valid, "motor_1": {"min": True, "max": 3000, "max_delta": 200}},
        {**valid, "motor_1": {"min": 100, "max": 4096, "max_delta": 200}},
        {**valid, "motor_1": {"min": 100, "max": 100, "max_delta": 200}},
    ]:
        p.write_text(json.dumps(broken))
        with pytest.raises(ValueError):
            config.load_limits(p)
