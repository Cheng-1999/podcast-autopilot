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
