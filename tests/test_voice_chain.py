from pathlib import Path

from podcast_autopilot.config import AppConfig, VoiceChainConfig, load_config
from podcast_autopilot.ffmpeg import generate_synthetic_audio
from podcast_autopilot.voice_chain import build_filtergraph, clean_audio


def test_filtergraph_contains_tunable_cleanup_chain():
    graph = build_filtergraph(VoiceChainConfig())
    assert graph == (
        "highpass=f=80,deesser=f=0.5:i=0.3:m=0.5,"
        "acompressor=threshold=0.125893:ratio=3:attack=15:release=250:makeup=1.0"
    )


def test_afftdn_fallback_produces_loudness_and_receipt(tmp_path: Path):
    source = tmp_path / "synthetic.wav"
    generate_synthetic_audio(source, duration=30)
    config = AppConfig(voice_chain=VoiceChainConfig(denoise_engine="afftdn"))
    output, receipt = clean_audio(source, tmp_path / "out", config)
    assert output.is_file()
    data = __import__("json").loads(receipt.read_text(encoding="utf-8"))
    assert data["engine"]["name"] == "afftdn"
    assert data["denoise_filtergraph"] == "afftdn=nr=12:nf=-25"
    assert abs(data["verification"]["lufs"] + 16) <= 1.0
    assert data["verification"]["true_peak_dbtp"] <= -1.0


def test_profile_loads_denoise_and_spotify_target(tmp_path: Path):
    path = tmp_path / "profile.yaml"
    path.write_text("name: spotify\ndenoise:\n  engine: afftdn\nvoice_chain:\n  loudness_target_i: -14\n", encoding="utf-8")
    config = load_config(path)
    assert config.voice_chain.denoise_engine == "afftdn"
    assert config.voice_chain.loudness_target_i == -14


def test_quiet_take_with_full_scale_transient_hits_targets(tmp_path: Path):
    """A -35 LUFS home recording with a single 0 dBFS mic bump (real EP3-1's
    shape). ffmpeg's loudnorm cannot normalise this (linear mode reverts to
    dynamic, which undershoots), and the deesser goes unstable once pre-gain
    pushes the bump past 0 dBFS -- both must be handled by the chain.
    """
    from podcast_autopilot.ffmpeg import run_ffmpeg

    source = tmp_path / "quiet-with-bump.wav"
    run_ffmpeg([
        "-f", "lavfi", "-i", "sine=frequency=220:duration=20",
        "-f", "lavfi", "-i", "anoisesrc=duration=20:color=pink:amplitude=0.02",
        "-f", "lavfi", "-i", "sine=frequency=60:duration=20",
        "-filter_complex",
        # lavfi `sine` is 1/8 full scale; amix halves each input: bed lands
        # near -35 LUFS, plus a 20 ms burst at ~0 dBFS at t=7s (a mic bump).
        "[0:a][1:a]amix=inputs=2:duration=first,volume=0.56[quiet];"
        "[2:a]volume='if(between(t,7,7.02),8,0)':eval=frame[bump];"
        "[quiet][bump]amix=inputs=2:duration=first:normalize=0[out]",
        "-map", "[out]", "-ar", "44100", "-ac", "1", "-c:a", "pcm_f32le", str(source),
    ])
    config = AppConfig(voice_chain=VoiceChainConfig(denoise_engine="off"))
    output, receipt = clean_audio(source, tmp_path / "out", config)
    data = __import__("json").loads(receipt.read_text(encoding="utf-8"))
    assert -40 <= float(data["input_loudness"]["input_i"]) <= -30
    assert float(data["input_loudness"]["input_tp"]) >= -3.0  # the bump is really there
    assert 12 <= data["gain"]["pregain_db"] <= 24
    assert abs(data["gain"]["gain_db"]) <= 12  # the chain itself does not collapse the bed
    assert abs(data["verification"]["lufs"] + 16) <= 1.0
    assert data["verification"]["true_peak_dbtp"] <= -1.0
    assert "alimiter" in data["filtergraph"]
    assert output.is_file()


def test_gain_helpers_clamp_and_ignore_unmeasurable_input():
    from podcast_autopilot.voice_chain import MAX_GAIN_DB, _gain_to_target_db, _within_targets

    assert _gain_to_target_db(-16.0, "-34.6") == 18.6
    assert _gain_to_target_db(-16.0, "-inf") == 0.0
    assert _gain_to_target_db(-16.0, None) == 0.0
    assert _gain_to_target_db(-16.0, -90.0) == MAX_GAIN_DB
    profile = VoiceChainConfig()
    assert _within_targets(-16.4, -2.4, profile)
    assert not _within_targets(-19.5, -2.4, profile)
    assert not _within_targets(-16.0, -0.5, profile)
