import pytest

from rk import config


def write(tmp, text):
    p = tmp / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_defaults_and_paths(tmp_path, monkeypatch):
    home = tmp_path / "Пользователь Тест" / "Redakciya"
    home.mkdir(parents=True)
    monkeypatch.setenv("REDAKCIYA_HOME", str(home))
    monkeypatch.setenv("REDAKCIYA_SECRETS", str(tmp_path / "secrets"))
    c = config.load(write(home, "author: Тест\nplatforms:\n  tg: {mode: web, channel: '@t'}\n  max: {channel_id: -1}\n"))
    assert config.home() == home
    assert c.publish_order[:4] == ["max", "vk", "fb", "yt"]
    assert c.enabled == ["tg", "max"]
    assert c.defaults == ["tg", "max"]
    assert c.reverse_order == ["vkch"]


def test_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("REDAKCIYA_SECRETS", str(tmp_path))
    (tmp_path / "max_token").write_text(" abc \n", encoding="utf-8")
    c = config.load(write(tmp_path, "platforms: {max: {token_file: max_token}}\n"))
    assert c.secret("max_token") == "abc"
    with pytest.raises(config.ConfigError, match="rk login"):
        c.secret("nope")


def test_unknown_platform(tmp_path):
    with pytest.raises(config.ConfigError, match="неизвестная площадка"):
        config.load(write(tmp_path, "platforms: {facebook: {}}\n"))


def test_missing_config(tmp_path, monkeypatch):
    monkeypatch.setenv("REDAKCIYA_HOME", str(tmp_path))
    with pytest.raises(config.ConfigError, match="rk setup"):
        config.load()


def test_chat_link(tmp_path):
    c = config.load(write(tmp_path, "platforms: {tg: {}}\nclosing: {chat: {tg: 'https://t.me/x'}}\n"))
    assert c.chat_link("tg") == "https://t.me/x" and c.chat_link("vk") == ""
