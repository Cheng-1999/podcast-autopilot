from __future__ import annotations

import json
from pathlib import Path

import yaml

from podcast_autopilot import run as run_mod
from podcast_autopilot.config import AppConfig
from podcast_autopilot.ffmpeg import generate_synthetic_audio


def _make_episode(tmp_path: Path) -> Path:
    for name in ("part1.wav", "part2.wav"):
        generate_synthetic_audio(tmp_path / name, duration=3.0)
    manifest = {
        "title": "Test Episode",
        "episode": 1,
        "parts": ["part1.wav", "part2.wav"],
    }
    episode_yaml = tmp_path / "episode.yaml"
    episode_yaml.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return episode_yaml


def test_run_episode_end_to_end_produces_report_and_mp3(tmp_path: Path):
    episode_yaml = _make_episode(tmp_path)
    config = AppConfig()
    out_dir = tmp_path / "out"

    report = run_mod.run_episode(
        episode_yaml, config, profile_name="default", profile_config_path=None,
        model_size="small", out_dir=out_dir,
    )

    assert len(report.parts) == 2
    for part in report.parts:
        assert part.edited_wav.is_file()
        assert part.transcript_path.is_file()
        statuses = {s.name: s.status for s in part.stages}
        assert statuses["probe"] == "ran"
        assert statuses["apply"] == "ran"
    assert report.assemble_result is not None
    output_mp3 = Path(report.assemble_result["output"])
    assert output_mp3.is_file()
    assert output_mp3.suffix == ".mp3"

    report_path = run_mod.write_run_report(report, report.episode_root / "RUN_REPORT.md")
    text = report_path.read_text(encoding="utf-8")
    assert "# Run Report" in text
    assert "Re-apply after editing plan.json" in text
    assert run_mod.reapply_command(report) in text


def test_run_episode_second_run_hits_cache_for_every_stage(tmp_path: Path):
    episode_yaml = _make_episode(tmp_path)
    config = AppConfig()
    out_dir = tmp_path / "out"

    run_mod.run_episode(
        episode_yaml, config, profile_name="default", profile_config_path=None,
        model_size="small", out_dir=out_dir,
    )
    second = run_mod.run_episode(
        episode_yaml, config, profile_name="default", profile_config_path=None,
        model_size="small", out_dir=out_dir,
    )

    for part in second.parts:
        statuses = {s.name: s.status for s in part.stages}
        for stage in ("clean", "plan-pauses", "transcribe", "plan-fillers", "audit", "apply"):
            assert statuses[stage] == "cached", (stage, statuses)
    assert second.assemble_stage.status == "cached"


def test_run_episode_force_reruns_everything(tmp_path: Path):
    episode_yaml = _make_episode(tmp_path)
    config = AppConfig()
    out_dir = tmp_path / "out"

    run_mod.run_episode(
        episode_yaml, config, profile_name="default", profile_config_path=None,
        model_size="small", out_dir=out_dir,
    )
    forced = run_mod.run_episode(
        episode_yaml, config, profile_name="default", profile_config_path=None,
        model_size="small", out_dir=out_dir, force=True,
    )

    for part in forced.parts:
        statuses = {s.name: s.status for s in part.stages}
        for stage in ("clean", "plan-pauses", "transcribe", "plan-fillers", "audit", "apply"):
            assert statuses[stage] == "ran", (stage, statuses)
    assert forced.assemble_stage.status == "ran"


def test_run_episode_dry_run_previews_without_side_effects(tmp_path: Path):
    episode_yaml = _make_episode(tmp_path)
    config = AppConfig()
    out_dir = tmp_path / "out"

    report = run_mod.run_episode(
        episode_yaml, config, profile_name="default", profile_config_path=None,
        model_size="small", out_dir=out_dir, dry_run=True,
    )

    assert not out_dir.exists() or not any(out_dir.rglob("*.wav"))
    for part in report.parts:
        for stage in part.stages:
            assert stage.status in ("planned", "cached")
    assert report.assemble_stage.status == "planned"


def test_run_episode_editing_plan_json_only_invalidates_audit_apply_assemble(tmp_path: Path):
    episode_yaml = _make_episode(tmp_path)
    config = AppConfig()
    out_dir = tmp_path / "out"

    run_mod.run_episode(
        episode_yaml, config, profile_name="default", profile_config_path=None,
        model_size="small", out_dir=out_dir,
    )

    part1_dir = out_dir / "episode" / "parts" / "part1"
    plan_path = part1_dir / "plan.json"
    plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_data["items"][0]["enabled"] = plan_data["items"][0].get("enabled", True)
    plan_path.write_text(json.dumps(plan_data), encoding="utf-8")

    second = run_mod.run_episode(
        episode_yaml, config, profile_name="default", profile_config_path=None,
        model_size="small", out_dir=out_dir,
    )
    part1 = next(p for p in second.parts if p.stem == "part1")
    statuses = {s.name: s.status for s in part1.stages}
    assert statuses["clean"] == "cached"
    assert statuses["plan-pauses"] == "cached"
    assert statuses["transcribe"] == "cached"
    assert statuses["plan-fillers"] == "cached"
    assert statuses["audit"] == "ran"
    assert statuses["apply"] == "ran"
    # assemble's cache key is the content hash of the edited parts, not the plan
    # text, so a plan edit that renders byte-identical audio correctly still
    # hits the assemble cache -- only a plan edit that changes the rendered
    # output would invalidate it too.


def test_run_episode_unknown_skip_stage_raises(tmp_path: Path):
    episode_yaml = _make_episode(tmp_path)
    config = AppConfig()
    try:
        run_mod.run_episode(
            episode_yaml, config, profile_name="default", profile_config_path=None,
            model_size="small", out_dir=tmp_path / "out", skip=["not-a-stage"],
        )
        assert False, "expected RunError"
    except run_mod.RunError as exc:
        assert "unknown --skip stage" in str(exc)


def test_run_episode_probe_is_cached_and_restored_on_second_run(tmp_path: Path):
    episode_yaml = _make_episode(tmp_path)
    config = AppConfig()
    out_dir = tmp_path / "out"

    first = run_mod.run_episode(
        episode_yaml, config, profile_name="default", profile_config_path=None,
        model_size="small", out_dir=out_dir,
    )
    second = run_mod.run_episode(
        episode_yaml, config, profile_name="default", profile_config_path=None,
        model_size="small", out_dir=out_dir,
    )
    for before, after in zip(first.parts, second.parts):
        assert {s.name: s.status for s in before.stages}["probe"] == "ran"
        assert {s.name: s.status for s in after.stages}["probe"] == "cached"
        # The cached probe is restored, so the report still shows "before" loudness.
        assert after.probe_before == before.probe_before
        assert after.probe_before["input_i"] == before.probe_before["input_i"]


def test_run_episode_changing_model_invalidates_transcribe_cache_only(tmp_path: Path):
    episode_yaml = _make_episode(tmp_path)
    config = AppConfig()
    out_dir = tmp_path / "out"

    run_mod.run_episode(
        episode_yaml, config, profile_name="default", profile_config_path=None,
        model_size="small", out_dir=out_dir,
    )
    # Preview only (medium would download a second model): a different model
    # must be a cache miss for transcribe while clean/plan-pauses stay cached.
    preview = run_mod.run_episode(
        episode_yaml, config, profile_name="default", profile_config_path=None,
        model_size="medium", out_dir=out_dir, dry_run=True,
    )
    for part in preview.parts:
        statuses = {s.name: s.status for s in part.stages}
        assert statuses["clean"] == "cached"
        assert statuses["plan-pauses"] == "cached"
        assert statuses["transcribe"] == "planned", statuses
    same_model = run_mod.run_episode(
        episode_yaml, config, profile_name="default", profile_config_path=None,
        model_size="small", out_dir=out_dir, dry_run=True,
    )
    for part in same_model.parts:
        assert {s.name: s.status for s in part.stages}["transcribe"] == "cached"
    cache = json.loads((out_dir / "episode" / "parts" / "part1" / "stage_cache.json").read_text(encoding="utf-8"))
    assert cache["transcribe"]["model_size"] == "small"


def test_run_report_records_loudness_before_and_after_clean(tmp_path: Path):
    episode_yaml = _make_episode(tmp_path)
    config = AppConfig()
    out_dir = tmp_path / "out"

    report = run_mod.run_episode(
        episode_yaml, config, profile_name="default", profile_config_path=None,
        model_size="small", out_dir=out_dir,
    )
    for part in report.parts:
        assert part.loudness_after_clean is not None
        assert part.loudness_after_clean["source"] == "clean_receipt"
        assert abs(part.loudness_after_clean["input_i"] - config.voice_chain.loudness_target_i) <= 1.0
    text = run_mod.write_run_report(report, report.episode_root / "RUN_REPORT.md").read_text(encoding="utf-8")
    assert "Loudness before clean:" in text
    assert "Loudness after clean:" in text
    assert "Loudness after clean: n/a" not in text


def test_reapply_command_pins_model_out_dir_config_and_skips(tmp_path: Path):
    episode_yaml = tmp_path / "ep.yaml"
    profile_path = tmp_path / "custom.yaml"
    report = run_mod.RunReport(
        episode_yaml=episode_yaml,
        profile="default",
        profile_config_path=profile_path,
        episode_root=tmp_path / "out" / "ep",
        model_size="medium",
        out_dir=tmp_path / "out",
        skip=["transcribe"],
    )
    cmd = run_mod.reapply_command(report)
    assert cmd.startswith(f'python -m podcast_autopilot run "{episode_yaml}"')
    assert "--profile default" in cmd
    assert "--model medium" in cmd
    assert f'--out-dir "{tmp_path / "out"}"' in cmd
    assert f'--config "{profile_path}"' in cmd
    assert "--skip transcribe" in cmd

    builtin = run_mod.RunReport(
        episode_yaml=episode_yaml, profile="default", profile_config_path=None,
        episode_root=tmp_path / "out" / "ep",
    )
    assert "--config" not in run_mod.reapply_command(builtin)


def test_run_episode_report_carries_reapply_settings(tmp_path: Path):
    episode_yaml = _make_episode(tmp_path)
    out_dir = tmp_path / "out"
    report = run_mod.run_episode(
        episode_yaml, AppConfig(), profile_name="default", profile_config_path=None,
        model_size="small", out_dir=out_dir, skip=["assemble"], dry_run=True,
    )
    assert report.model_size == "small"
    assert report.out_dir == out_dir
    assert report.skip == ["assemble"]
    assert f'--out-dir "{out_dir}"' in run_mod.reapply_command(report)


def test_run_episode_plan_fillers_reruns_when_plan_pauses_was_invalidated(tmp_path: Path, monkeypatch):
    """A rebuilt pause plan is a fresh pause-only plan.json; plan-fillers must
    merge its proposals into it again even though its own key (clean wav +
    transcript) is unchanged, otherwise the proposals silently vanish."""
    episode_yaml = _make_episode(tmp_path)
    config = AppConfig()
    out_dir = tmp_path / "out"

    run_mod.run_episode(
        episode_yaml, config, profile_name="default", profile_config_path=None,
        model_size="small", out_dir=out_dir,
    )
    monkeypatch.setitem(run_mod.STAGE_VERSIONS, "plan-pauses", run_mod.STAGE_VERSIONS["plan-pauses"] + 1)
    second = run_mod.run_episode(
        episode_yaml, config, profile_name="default", profile_config_path=None,
        model_size="small", out_dir=out_dir,
    )
    for part in second.parts:
        statuses = {s.name: s.status for s in part.stages}
        assert statuses["clean"] == "cached"
        assert statuses["transcribe"] == "cached"
        assert statuses["plan-pauses"] == "ran"
        assert statuses["plan-fillers"] == "ran"
        assert statuses["apply"] == "ran"
