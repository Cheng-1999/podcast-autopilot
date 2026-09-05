from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from . import apply as apply_mod
from . import audit as audit_mod
from . import plan as plan_mod
from . import probe as probe_mod
from . import receipts as receipts_mod
from . import transcribe as transcribe_mod
from . import voice_chain as voice_chain_mod
from .config import AppConfig, load_config
from .ffmpeg import generate_synthetic_audio
from .pauses import write_pause_plan

app = typer.Typer(add_completion=False, help="podcast-autopilot: CPU-only podcast post-production autopilot")


def _load_app_config(config_path: Optional[Path]) -> AppConfig:
    return load_config(config_path)


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


@app.command()
def clean(
    audio_path: Path = typer.Argument(..., exists=True, readable=True),
    profile: str = typer.Option("default", "--profile"),
    out_dir: Path = typer.Option(Path("out"), "--out-dir"),
    config_path: Optional[Path] = typer.Option(None, "--config"),
) -> None:
    """Denoise, clean, compress, and loudness-normalize an audio file."""
    if config_path is None:
        profile_path = Path("profiles") / f"{profile}.yaml"
        if not profile_path.is_file():
            profile_path = Path("profiles") / f"{profile}.example.yaml"
        config_path = profile_path if profile_path.is_file() else None
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


if __name__ == "__main__":
    app()
