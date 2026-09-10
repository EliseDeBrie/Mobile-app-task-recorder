import json

import numpy as np
import pytest

from conftest import make_screen

from whs_recorder.redaction import (
    RedactionConfig,
    RegionRule,
    TextRule,
    load_redaction_config,
)


def config(**kwargs) -> RedactionConfig:
    return RedactionConfig.from_dict(kwargs)


def test_relative_region_is_masked(screen):
    cfg = config(regions=[{"name": "user", "box": [0.0, 0.0, 1.0, 0.1]}])
    out = cfg.apply(screen)

    assert (out[: int(0.1 * screen.shape[0])] == 0).all()
    assert np.array_equal(out[int(0.1 * screen.shape[0]) + 1 :], screen[int(0.1 * screen.shape[0]) + 1 :])


def test_absolute_region_is_masked(screen):
    cfg = config(regions=[{"name": "badge", "box": [10, 20, 60, 40], "units": "absolute"}])
    out = cfg.apply(screen)

    assert (out[20:40, 10:60] == 0).all()
    assert np.array_equal(out[41:, :], screen[41:, :])


def test_apply_does_not_modify_the_input(screen):
    before = screen.copy()
    config(regions=[{"name": "all", "box": [0, 0, 1, 1]}]).apply(screen)
    assert np.array_equal(screen, before)


@pytest.mark.parametrize("mode", ["blur", "pixelate"])
def test_soft_modes_change_the_region_without_blanking_it(screen, mode):
    cfg = config(regions=[{"name": "r", "box": [0.1, 0.1, 0.9, 0.4], "mode": mode}])
    out = cfg.apply(screen)
    region = out[64:256, 36:324]

    assert not np.array_equal(region, screen[64:256, 36:324])
    assert region.max() > 0  # not simply blacked out


def test_default_mode_applies_to_rules_without_one(screen):
    cfg = config(default_mode="blur", regions=[{"name": "r", "box": [0, 0, 1, 0.2]}])
    assert cfg.regions[0].mode == "blur"


def test_out_of_frame_boxes_are_clamped(screen):
    cfg = config(regions=[{"name": "r", "box": [-50, -50, 9999, 30], "units": "absolute"}])
    out = cfg.apply(screen)
    assert (out[0:30, :] == 0).all()


def test_reversed_box_is_normalised(screen):
    cfg = config(regions=[{"name": "r", "box": [80, 60, 20, 10], "units": "absolute"}])
    out = cfg.apply(screen)
    assert (out[10:60, 20:80] == 0).all()


def test_labels_outline_the_redacted_area(screen):
    out = config(label=True, regions=[{"name": "user", "box": [0.0, 0.0, 1.0, 0.1]}]).apply(screen)
    reds = (out[:, :, 2] > 200) & (out[:, :, 0] < 60) & (out[:, :, 1] < 60)
    assert reds.any()


def test_empty_config_returns_the_frame_unchanged(screen):
    cfg = config()
    assert cfg.is_empty()
    assert cfg.apply(screen) is screen


def test_relative_box_outside_the_unit_range_is_rejected():
    with pytest.raises(ValueError, match="relative units"):
        config(regions=[{"name": "r", "box": [0, 0, 1200, 40]}])


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="Unknown redaction mode"):
        config(regions=[{"name": "r", "box": [0, 0, 1, 1], "mode": "scribble"}])


def test_unknown_units_are_rejected():
    with pytest.raises(ValueError, match="Unknown units"):
        config(regions=[{"name": "r", "box": [0, 0, 1, 1], "units": "inches"}])


def test_missing_box_is_rejected():
    with pytest.raises(ValueError, match="box"):
        config(regions=[{"name": "r"}])


def test_bad_text_pattern_is_rejected():
    with pytest.raises(Exception):
        config(text_patterns=[{"name": "r", "pattern": "LP[0-9"}])


def test_missing_text_pattern_is_rejected():
    with pytest.raises(ValueError, match="pattern"):
        config(text_patterns=[{"name": "r"}])


def test_text_rules_are_skipped_when_ocr_is_unavailable(screen, monkeypatch, capsys):
    import whs_recorder.redaction as redaction

    monkeypatch.setattr(redaction, "words_with_boxes", lambda frame, conf: [])

    out = config(text_patterns=[{"name": "lp", "pattern": "LP[0-9]+"}]).apply(screen)
    assert np.array_equal(out, screen)


def test_text_rule_masks_the_matching_word(screen, monkeypatch):
    import whs_recorder.redaction as redaction

    monkeypatch.setattr(
        redaction, "words_with_boxes",
        lambda frame, conf: [("LP123456", (40, 50, 90, 20)), ("Confirm", (40, 90, 70, 20))],
    )

    out = config(text_patterns=[{"name": "lp", "pattern": "LP[0-9]{6}", "padding": 0}]).apply(screen)

    assert (out[50:70, 40:130] == 0).all()
    assert np.array_equal(out[90:110, 40:110], screen[90:110, 40:110])


def test_region_and_text_rules_combine(screen, monkeypatch):
    import whs_recorder.redaction as redaction

    monkeypatch.setattr(redaction, "words_with_boxes", lambda frame, conf: [("LP999999", (40, 300, 90, 20))])

    cfg = config(
        regions=[{"name": "header", "box": [0.0, 0.0, 1.0, 0.05]}],
        text_patterns=[{"name": "lp", "pattern": "LP[0-9]+", "padding": 0}],
    )
    out = cfg.apply(screen)

    assert (out[0:32, :] == 0).all()
    assert (out[300:320, 40:130] == 0).all()
    assert cfg.describe() == "1 region rule(s), 1 text rule(s)"


def test_config_round_trips_through_a_file(tmp_path, screen):
    path = tmp_path / "redaction.json"
    path.write_text(json.dumps({"regions": [{"name": "r", "box": [0, 0, 1, 0.1]}]}), encoding="utf-8")

    cfg = load_redaction_config(str(path))

    assert isinstance(cfg, RedactionConfig)
    assert (cfg.apply(screen)[0:64] == 0).all()


def test_no_config_path_means_no_redaction():
    assert load_redaction_config(None) is None
    assert load_redaction_config("") is None


def test_sample_config_in_examples_is_valid(screen, repo_root):
    cfg = load_redaction_config(str(repo_root / "examples" / "redaction.sample.json"))
    assert cfg is not None and not cfg.is_empty()
    assert cfg.apply(screen).shape == screen.shape
