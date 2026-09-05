from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from . import apply as apply_mod
from . import audit as audit_mod
from . import plan as plan_mod
from . import probe as probe_mod
from . import receipts as receipts_mod
from .config import AppConfig, load_config
from .ffmpeg import generate_synthetic_audio

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
