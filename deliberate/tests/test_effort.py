from deliberate.effort import Effort, parse_effort, resolve_effort, split_model_effort


def test_parse_effort_names_and_ints():
    assert parse_effort("high") is Effort.HIGH
    assert parse_effort("OFF") is Effort.OFF
    assert parse_effort(2) is Effort.MEDIUM
    assert parse_effort(None) is None
    assert parse_effort("banana") is None


def test_split_model_effort_recognises_suffix():
    assert split_model_effort("qwen3.5:high") == ("qwen3.5", Effort.HIGH)
    assert split_model_effort("base:off") == ("base", Effort.OFF)


def test_split_model_effort_leaves_non_effort_tags_alone():
    # A real model tag like a quant level must not be eaten as an effort suffix.
    assert split_model_effort("qwen3.5:q4") == ("qwen3.5:q4", None)
    assert split_model_effort("qwen3.5") == ("qwen3.5", None)


def test_resolve_effort_precedence():
    # explicit field beats suffix beats default
    assert resolve_effort("low", Effort.HIGH, Effort.MEDIUM) is Effort.LOW
    assert resolve_effort(None, Effort.HIGH, Effort.MEDIUM) is Effort.HIGH
    assert resolve_effort(None, None, Effort.MEDIUM) is Effort.MEDIUM


def test_resolve_effort_off_is_not_treated_as_falsy():
    # Effort.OFF == 0; an explicit off must win, not fall through to the default.
    assert resolve_effort(None, Effort.OFF, Effort.MEDIUM) is Effort.OFF
    assert resolve_effort("off", None, Effort.HIGH) is Effort.OFF
