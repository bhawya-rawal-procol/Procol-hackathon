"""The .env loader: parsing rules, and the guarantee that a real shell variable always wins."""
import os

from vi import env


def test_parse_handles_comments_quotes_and_export():
    got = env.parse("\n".join([
        "# a comment", "", "ANTHROPIC_API_KEY=sk-ant-abc",
        "export VI_PORT=8010", 'VI_ANTHROPIC_MODEL="claude-sonnet-4-5"',
        "QUOTED='single'", "TRAILING=value # inline comment", "NOT_A_PAIR",
    ]))
    assert got == {"ANTHROPIC_API_KEY": "sk-ant-abc", "VI_PORT": "8010",
                   "VI_ANTHROPIC_MODEL": "claude-sonnet-4-5", "QUOTED": "single",
                   "TRAILING": "value"}


def test_load_sets_missing_and_never_clobbers_the_real_environment(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("VI_TEST_NEW=from_file\nVI_TEST_EXISTING=from_file\n")
    monkeypatch.setenv("VI_TEST_EXISTING", "from_shell")
    monkeypatch.delenv("VI_TEST_NEW", raising=False)

    applied = env.load(f)

    assert applied == {"VI_TEST_NEW": "from_file"}
    assert os.environ["VI_TEST_NEW"] == "from_file"
    assert os.environ["VI_TEST_EXISTING"] == "from_shell"


def test_load_is_a_noop_without_a_file(tmp_path):
    assert env.load(tmp_path / "absent.env") == {}


def test_blank_value_does_not_mask_a_real_key(tmp_path, monkeypatch):
    """.env ships with ANTHROPIC_API_KEY= blank; that must not wipe an exported key."""
    f = tmp_path / ".env"
    f.write_text("ANTHROPIC_API_KEY=\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
    env.load(f)
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-real"
