import os

os.environ["AWS_REGION"] = "us-west-2"  # Test env override

from quarry.config import Settings, load_config


def test_settings_defaults():
    settings = Settings()
    assert settings.db_path == "quarry.db"
    assert settings.similarity_threshold == 0.35


def test_load_config_from_yaml(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
db_path: test.db
similarity_threshold: 0.5
""")
    settings = load_config(config_file)
    assert settings.db_path == "test.db"
    assert settings.similarity_threshold == 0.5


def test_env_var_overrides_yaml(tmp_path):
    """Env vars should override YAML values"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
db_path: yaml-value.db
aws_region: yaml-region
""")
    # AWS_REGION is set in environment at top of file
    settings = load_config(config_file)
    # Env var should win
    assert settings.aws_region == "us-west-2"
