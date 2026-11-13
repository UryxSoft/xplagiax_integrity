import pytest

from integrity.config import ConfigError, Settings

GOOD_PEPPER = "x" * 32


def test_defaults_are_valid_for_development():
    Settings().validate()


def test_from_env_reads_prefixed_variables():
    s = Settings.from_env({"XI_ENV": "testing", "XI_LOG_LEVEL": "warning", "XI_DB_POOL_SIZE": "3"})
    assert (s.env, s.log_level, s.db_pool_size) == ("testing", "WARNING", 3)


def test_non_integer_is_rejected():
    with pytest.raises(ConfigError):
        Settings.from_env({"XI_DB_POOL_SIZE": "many"})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"api_key_pepper": ""},
        {"api_key_pepper": "short"},
        {"database_url": "sqlite:///prod.db"},
        {"log_level": "DEBUG"},
    ],
)
def test_production_refuses_unsafe_settings(kwargs):
    base = {"env": "production", "api_key_pepper": GOOD_PEPPER, "database_url": "mysql+pymysql://u:p@h/db"}
    base.update(kwargs)
    with pytest.raises(ConfigError):
        Settings(**base).validate()


def test_production_accepts_safe_settings():
    Settings(env="production", api_key_pepper=GOOD_PEPPER, database_url="mysql+pymysql://u:p@h/db").validate()


def test_unknown_env_rejected():
    with pytest.raises(ConfigError):
        Settings(env="staging").validate()


def test_public_dict_hides_secrets():
    d = Settings(api_key_pepper=GOOD_PEPPER, database_url="mysql+pymysql://u:secretpw@h/db").public_dict()
    assert "api_key_pepper" not in d and "database_url" not in d
    assert "secretpw" not in repr(Settings(database_url="x", api_key_pepper=GOOD_PEPPER).public_dict())


def test_pepper_not_in_repr():
    assert GOOD_PEPPER not in repr(Settings(api_key_pepper=GOOD_PEPPER))
