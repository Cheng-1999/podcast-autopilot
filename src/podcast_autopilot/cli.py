from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from . import apply as apply_mod
from . import assemble as assemble_mod
from . import audit as audit_mod
from . import clips as clips_mod
from . import plan as plan_mod
from . import probe as probe_mod
from . import receipts as receipts_mod
from . import run as run_mod
from . import transcribe as transcribe_mod
from . import voice_chain as voice_chain_mod
from .config import AppConfig, load_config
from .ffmpeg import generate_synthetic_audio
from .pauses import write_pause_plan

app = typer.Typer(add_completion=False, help="podcast-autopilot: CPU-only podcast post-production autopilot")


def _load_app_config(config_path: Optional[Path]) -> AppConfig:
    return load_config(config_path)


VALID_WHISPER_MODEL_SIZES = ("small", "medium")


def _validate_model_size(model: Optional[str]) -> None:
    if model is not None and model not in VALID_WHISPER_MODEL_SIZES:
        raise typer.BadParameter(
            f"must be one of {VALID_WHISPER_MODEL_SIZES}, got {model!r}", param_hint="--model"
        )


@app.command()
def probe(
    audio_path: Path = typer.Argument(..., exists=True, readable=True),
    config_path: Optional[Path] = typer.Option(None, "--config", help="Path to a config YAML file"),
) -> None:
    """Print ffprobe + integrated loudness info for an audio file as JSON."""
    config = _load_app_config(config_path)
    info = probe_mod.probe_audio(audio_path, config)
    typer.echo(json.dumps(info, indent=2, ensure_ascii=False))


@app.command("plan-pauses")
def plan_pauses(
    audio_path: Path = typer.Argument(..., exists=True, readable=True),
    out_dir: Path = typer.Option(Path("out"), "--out-dir"),
    config_path: Optional[Path] = typer.Option(None, "--config"),
) -> None:
    """Detect long pauses and write an auditable edit plan."""
    config = _load_app_config(config_path)
    plan_path, plan = write_pause_plan(audio_path, out_dir, config)
    removed = sum(item.end - item.start for item in plan.items if item.enabled and item.kind == "cut")
    new_duration = plan.predicted_duration if plan.predicted_duration is not None else plan.source.duration - removed
    typer.echo("cuts | seconds removed | new duration")
    typer.echo(f"{sum(item.kind == 'cut' and item.enabled for item in plan.items):5d} | {removed:15.3f} | {new_duration:11.3f}")
    typer.echo(f"plan: {plan_path}")


@app.command()
def apply(
    plan_path: Path = typer.Argument(..., exists=True, readable=True),
    audio_path: Path = typer.Argument(..., exists=True, readable=True),
    out_dir: Path = typer.Option(Path("out"), "--out-dir"),
    config_path: Optional[Path] = typer.Option(None, "--config"),
) -> None:
    """Audit and render an edit plan, then write its receipt."""
    config = _load_app_config(config_path)
    plan = plan_mod.load_plan(plan_path)
    result = audit_mod.audit_plan(plan, audio_path)
    if not result.ok:
        typer.echo("AUDIT FAILED:\n" + "\n".join(result.errors), err=True)
        raise typer.Exit(code=1)
    output = apply_mod.apply_plan(plan, audio_path, out_dir, config)
    receipt = receipts_mod.write_receipt(plan, audio_path, plan_path, output, output.parent, config)
    typer.echo(f"output: {output}\nreceipt: {receipt}\nseconds removed: {result.total_cut_duration:.3f}")


@app.command()
def transcribe(
    audio_path: Path = typer.Argument(..., exists=True, readable=True),
    model: Optional[str] = typer.Option(None, "--model", help="small|medium (default: config.whisper_model_size, else small)"),
    out_dir: Path = typer.Option(Path("out"), "--out-dir"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="Path to a config YAML file"),
) -> None:
    """Transcribe audio to zh-TW (faster-whisper, CPU int8) and write transcript.json/.srt/.md."""
    _validate_model_size(model)
    config = _load_app_config(config_path)
    model_size = model or config.whisper_model_size

    target_dir = Path(out_dir) / audio_path.stem
    target_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    data = transcribe_mod.transcribe_audio(audio_path, model_size=model_size, config=config)
    elapsed = time.monotonic() - started

    transcribe_mod.save_transcript(data, target_dir / "transcript.json")
    transcribe_mod.write_srt(data["segments"], target_dir / "transcript.srt")
    transcribe_mod.write_markdown(data["segments"], target_dir / "transcript.md")

    typer.echo(
        f"TRANSCRIBE OK: model={model_size} language={data['language']} "
        f"segments={len(data['segments'])} opencc_chars_changed={data['opencc_chars_changed']} "
        f"elapsed={elapsed:.1f}s"
    )
    typer.echo(f"out: {target_dir}")


def _resolve_profile_config_path(profile: str) -> Optional[Path]:
    profile_path = Path("profiles") / f"{profile}.yaml"
    if not profile_path.is_file():
        profile_path = Path("profiles") / f"{profile}.example.yaml"
    return profile_path if profile_path.is_file() else None


@app.command()
def clean(
    audio_path: Path = typer.Argument(..., exists=True, readable=True),
    profile: str = typer.Option("default", "--profile"),
    out_dir: Path = typer.Option(Path("out"), "--out-dir"),
    config_path: Optional[Path] = typer.Option(None, "--config"),
) -> None:
    """Denoise, clean, compress, and loudness-normalize an audio file."""
    if config_path is None:
        config_path = _resolve_profile_config_path(profile)
    config = _load_app_config(config_path)
    try:
        output, receipt = voice_chain_mod.clean_audio(audio_path, out_dir, config)
    except voice_chain_mod.VoiceChainError as exc:
        typer.echo(f"CLEAN FAILED: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"CLEAN OK: output={output}\nreceipt={receipt}")


@app.command("plan-fillers")
def plan_fillers(
    audio_path: Path = typer.Argument(..., exists=True, readable=True),
    model: Optional[str] = typer.Option(None, "--model", help="small|medium (default: config.whisper_model_size, else small)"),
    out_dir: Path = typer.Option(Path("out"), "--out-dir"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="Path to a config YAML file"),
) -> None:
    """Detect filler words and add disabled 'filler' proposals to <stem>'s edit plan.

    Reuses out/<stem>/transcript.json if present instead of re-transcribing.
    """
    _validate_model_size(model)
    config = _load_app_config(config_path)
    model_size = model or config.whisper_model_size

    target_dir = Path(out_dir) / audio_path.stem
    target_dir.mkdir(parents=True, exist_ok=True)

    transcript_path = target_dir / "transcript.json"
    if transcript_path.is_file():
        data = transcribe_mod.load_transcript(transcript_path)
    else:
        data = transcribe_mod.transcribe_audio(audio_path, model_size=model_size, config=config)
        transcribe_mod.save_transcript(data, transcript_path)
        transcribe_mod.write_srt(data["segments"], target_dir / "transcript.srt")
        transcribe_mod.write_markdown(data["segments"], target_dir / "transcript.md")

    words = transcribe_mod.words_from_transcript(data)
    candidates = transcribe_mod.detect_fillers(
        words,
        filler_words=config.filler_words,
        pause_threshold_s=config.filler_pause_threshold_s,
        min_probability=config.filler_min_probability,
    )

    source_info = probe_mod.probe_audio(audio_path, config)
    source = plan_mod.SourceInfo(
        path=str(audio_path),
        sha256=audit_mod.sha256_of_file(audio_path),
        duration=source_info["duration"],
        sr=source_info["sr"],
        channels=source_info["channels"],
    )
    created = datetime.now(timezone.utc).isoformat()

    plan_path = target_dir / "plan.json"
    if plan_path.is_file():
        edit_plan = plan_mod.load_plan(plan_path)
    else:
        profile = plan_mod.ProfileInfo(name=config.profile_name, sha256=None)
        edit_plan = plan_mod.make_identity_keep_plan(source, profile, created)

    # Idempotent: re-running replaces stale disabled proposals instead of
    # appending duplicates (which would overlap and fail audit); matching
    # proposals and any human-enabled filler items are preserved.
    edit_plan.items = transcribe_mod.merge_filler_items(edit_plan.items, candidates)

    result = audit_mod.audit_plan(edit_plan, audio_path)
    if not result.ok:
        typer.echo("AUDIT FAILED:\n" + "\n".join(result.errors), err=True)
        raise typer.Exit(code=1)

    plan_mod.save_plan(edit_plan, plan_path)
    typer.echo(f"PLAN-FILLERS OK: {len(candidates)} filler proposals (disabled) written to {plan_path}")


@app.command()
def clips(
    audio_path: Path = typer.Argument(..., exists=True, readable=True),
    model: Optional[str] = typer.Option(None, "--model", help="small|medium (default: config.whisper_model_size, else small)"),
    render: bool = typer.Option(False, "--render", help="Also cut each candidate to out/<stem>/clips/<n>.mp3 + .srt"),
    out_dir: Path = typer.Option(Path("out"), "--out-dir"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="Path to a config YAML file"),
) -> None:
    """Score transcript-driven clip candidates for social cuts; --render cuts each one to MP3+SRT.

    Reuses out/<stem>/transcript.json if present instead of re-transcribing. An
    optional LLM re-rank runs when ANTHROPIC_API_KEY is set; otherwise the local
    scorer's order is the result.
    """
    _validate_model_size(model)
    config = _load_app_config(config_path)
    model_size = model or config.whisper_model_size

    target_dir = Path(out_dir) / audio_path.stem
    target_dir.mkdir(parents=True, exist_ok=True)

    transcript_path = target_dir / "transcript.json"
    if transcript_path.is_file():
        data = transcribe_mod.load_transcript(transcript_path)
    else:
        data = transcribe_mod.transcribe_audio(audio_path, model_size=model_size, config=config)
        transcribe_mod.save_transcript(data, transcript_path)
        transcribe_mod.write_srt(data["segments"], target_dir / "transcript.srt")
        transcribe_mod.write_markdown(data["segments"], target_dir / "transcript.md")

    candidates = clips_mod.build_candidates(data, config)
    candidates = clips_mod.rerank_with_llm(candidates, config)

    source_info = probe_mod.probe_audio(audio_path, config)
    source = plan_mod.SourceInfo(
        path=str(audio_path),
        sha256=audit_mod.sha256_of_file(audio_path),
        duration=source_info["duration"],
        sr=source_info["sr"],
        channels=source_info["channels"],
    )

    clips_path = target_dir / "clips.json"
    clips_mod.write_clips_json(
        candidates,
        source={"path": str(audio_path), "sha256": source.sha256, "duration": source.duration},
        transcript_record={"path": str(transcript_path), "sha256": audit_mod.sha256_of_file(transcript_path)},
        keywords=config.clips.keywords if config.clips else [],
        out_path=clips_path,
    )

    plan_path = target_dir / "plan.json"
    if plan_path.is_file():
        edit_plan = plan_mod.load_plan(plan_path)
    else:
        created = datetime.now(timezone.utc).isoformat()
        profile = plan_mod.ProfileInfo(name=config.profile_name, sha256=None)
        edit_plan = plan_mod.make_identity_keep_plan(source, profile, created)

    edit_plan.items = clips_mod.merge_clip_items(edit_plan.items, candidates)

    result = audit_mod.audit_plan(edit_plan, audio_path)
    if not result.ok:
        typer.echo("AUDIT FAILED:\n" + "\n".join(result.errors), err=True)
        raise typer.Exit(code=1)
    plan_mod.save_plan(edit_plan, plan_path)

    typer.echo(f"CLIPS OK: {len(candidates)} candidate(s) written to {clips_path}")
    for c in candidates:
        typer.echo(f"  {c['id']}: [{c['start']:.1f}s-{c['end']:.1f}s] score={c['score']:.2f}")

    if render:
        clips_dir = target_dir / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        for idx, c in enumerate(candidates, start=1):
            clips_mod.render_clip(audio_path, c["start"], c["end"], clips_dir / f"{idx}.mp3", config)
            clips_mod.write_clip_srt(data["segments"], c["start"], c["end"], clips_dir / f"{idx}.srt")
        typer.echo(f"RENDER OK: {len(candidates)} clip(s) in {clips_dir}")


@app.command()
def selftest(
    out_dir: Path = typer.Option(Path("out"), "--out-dir"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="Path to a config YAML file"),
) -> None:
    """Generate a synthetic file and run probe -> plan -> audit -> apply -> receipt end to end."""
    config = _load_app_config(config_path)

    work_dir = Path(out_dir) / "_selftest"
    source_path = work_dir / "selftest_source.wav"
    generate_synthetic_audio(source_path, duration=30.0, config=config)

    source_info = probe_mod.probe_audio(source_path, config)

    source = plan_mod.SourceInfo(
        path=str(source_path),
        sha256=audit_mod.sha256_of_file(source_path),
        duration=source_info["duration"],
        sr=source_info["sr"],
        channels=source_info["channels"],
    )
    profile = plan_mod.ProfileInfo(name="selftest", sha256=None)
    created = datetime.now(timezone.utc).isoformat()
    edit_plan = plan_mod.make_identity_keep_plan(source, profile, created)

    plan_path = work_dir / "selftest.plan.json"
    plan_mod.save_plan(edit_plan, plan_path)

    loaded_plan = plan_mod.load_plan(plan_path)
    result = audit_mod.audit_plan(loaded_plan, source_path)
    if not result.ok:
        typer.echo("AUDIT FAILED:\n" + "\n".join(result.errors), err=True)
        raise typer.Exit(code=1)

    output_path = apply_mod.apply_plan(loaded_plan, source_path, out_dir, config)
    receipt_path = receipts_mod.write_receipt(
        loaded_plan, source_path, plan_path, output_path, output_path.parent, config
    )

    output_info = probe_mod.probe_audio(output_path, config)
    delta = abs(output_info["duration"] - source_info["duration"])
    if delta > 0.05:
        typer.echo(f"SELFTEST FAILED: duration delta {delta * 1000:.1f}ms exceeds 50ms tolerance", err=True)
        raise typer.Exit(code=1)

    typer.echo(
        f"SELFTEST OK: input={source_info['duration']:.3f}s output={output_info['duration']:.3f}s "
        f"delta={delta * 1000:.1f}ms"
    )
    typer.echo(f"receipt: {receipt_path}")


@app.command()
def assemble(
    episode_yaml: Path = typer.Argument(..., exists=True, readable=True),
    out_dir: Path = typer.Option(Path("out"), "--out-dir"),
    config_path: Optional[Path] = typer.Option(None, "--config"),
) -> None:
    """Join parts, intro/outro, ducked BGM and chapters into a tagged episode MP3."""
    config = _load_app_config(config_path)
    try:
        result = assemble_mod.assemble_episode(episode_yaml, out_dir, config)
    except assemble_mod.AssembleError as exc:
        typer.echo(f"ASSEMBLE FAILED: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"ASSEMBLE OK: output={result['output']} duration={result['duration']:.3f}s "
        f"lufs={result['loudness']['input_i']:.1f} tp={result['loudness']['input_tp']:.1f}"
    )
    typer.echo(f"receipt: {result['receipt']}")


@app.command()
def run(
    episode_yaml: Path = typer.Argument(..., exists=True, readable=True),
    profile: str = typer.Option("default", "--profile"),
    model: Optional[str] = typer.Option(None, "--model", help="small|medium (default: config.whisper_model_size, else small)"),
    out_dir: Path = typer.Option(Path("out"), "--out-dir"),
    skip: list[str] = typer.Option([], "--skip", help=f"Stage(s) to skip: {run_mod.ALL_STAGES}"),
    force: bool = typer.Option(False, "--force", help="Ignore cached stage outputs and rerun everything"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview which stages would run/be cached; no side effects"),
    config_path: Optional[Path] = typer.Option(None, "--config"),
) -> None:
    """Run the full per-part pipeline (probe->clean->plan-pauses->transcribe->
    plan-fillers->audit->apply) for every part in an episode manifest, then
    assemble. Stage outputs are cached; --force reruns everything. Writes
    <out-dir>/<episode>/RUN_REPORT.md.
    """
    _validate_model_size(model)
    profile_config_path = config_path if config_path is not None else _resolve_profile_config_path(profile)
    config = _load_app_config(profile_config_path)
    model_size = model or config.whisper_model_size

    try:
        report = run_mod.run_episode(
            episode_yaml,
            config,
            profile_name=profile,
            profile_config_path=profile_config_path,
            model_size=model_size,
            out_dir=out_dir,
            skip=skip,
            force=force,
            dry_run=dry_run,
        )
    except (run_mod.RunError, assemble_mod.AssembleError, voice_chain_mod.VoiceChainError) as exc:
        typer.echo(f"RUN FAILED: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    # A preview must not clobber the report of the last real run (its per-stage
    # timings are not recoverable from the cache), so it gets its own file.
    report_name = "RUN_REPORT.dry-run.md" if dry_run else "RUN_REPORT.md"
    report_path = run_mod.write_run_report(report, report.episode_root / report_name)
    typer.echo(f"RUN {'DRY-RUN ' if dry_run else ''}OK: report={report_path}")
    if report.assemble_result:
        typer.echo(f"output: {report.assemble_result['output']}")


EXAMPLE_PART_NAMES = ["example-part-1.wav", "example-part-2.wav"]
# Seconds per placeholder part; examples/episode.example.yaml's chapters must fit
# inside len(EXAMPLE_PART_NAMES) * EXAMPLE_PART_DURATION_S (tests/test_run.py).
EXAMPLE_PART_DURATION_S = 20.0


@app.command("make-example")
def make_example(
    out_dir: Path = typer.Option(Path("examples"), "--out-dir"),
    config_path: Optional[Path] = typer.Option(None, "--config"),
) -> None:
    """Generate the synthetic WAVs examples/episode.example.yaml's `parts` point at
    (tone + white noise, no real recording needed), so `run.ps1
    examples\\episode.example.yaml` works right after a fresh clone. Skips any
    file that already exists.
    """
    config = _load_app_config(config_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in EXAMPLE_PART_NAMES:
        path = out_dir / name
        if path.is_file():
            continue
        generate_synthetic_audio(path, duration=EXAMPLE_PART_DURATION_S, config=config)
        typer.echo(f"generated {path}")
    typer.echo("MAKE-EXAMPLE OK")


if __name__ == "__main__":
    app()
