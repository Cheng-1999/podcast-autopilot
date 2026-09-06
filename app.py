"""Streamlit control panel for podcast-autopilot.

Internal tool: pick an episode.yaml, run the pipeline, read RUN_REPORT.md,
review/enable-disable plan items per part, and re-apply after edits. No
custom styling -- this is meant to be functional, not pretty.

Run with: streamlit run app.py
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from podcast_autopilot import run as run_mod
from podcast_autopilot.config import load_config
from podcast_autopilot.plan import load_plan, save_plan

st.set_page_config(page_title="podcast-autopilot", layout="wide")
st.title("podcast-autopilot")

REPO_ROOT = Path(__file__).resolve().parent


def _resolve_profile_config_path(profile: str) -> Path | None:
    profile_path = REPO_ROOT / "profiles" / f"{profile}.yaml"
    if not profile_path.is_file():
        profile_path = REPO_ROOT / "profiles" / f"{profile}.example.yaml"
    return profile_path if profile_path.is_file() else None


def _run(episode_yaml: Path, profile: str, model_size: str, out_dir: Path, force: bool) -> run_mod.RunReport:
    profile_config_path = _resolve_profile_config_path(profile)
    config = load_config(profile_config_path)
    return run_mod.run_episode(
        episode_yaml,
        config,
        profile_name=profile,
        profile_config_path=profile_config_path,
        model_size=model_size,
        out_dir=out_dir,
        force=force,
    )


with st.sidebar:
    st.header("Episode")
    episode_yaml_str = st.text_input("episode.yaml path", value="examples/episode.example.yaml")
    profile = st.text_input("profile", value="default")
    model_size = st.selectbox("whisper model", ["small", "medium", "large-v3"], index=0)
    out_dir_str = st.text_input("out dir", value="out")
    force = st.checkbox("--force (ignore cache, rerun everything)", value=False)
    run_clicked = st.button("Run", type="primary")

episode_yaml = Path(episode_yaml_str)
out_dir = Path(out_dir_str)
episode_root = out_dir / episode_yaml.stem
report_path = episode_root / "RUN_REPORT.md"

if run_clicked:
    if not episode_yaml.is_file():
        st.error(f"episode.yaml not found: {episode_yaml}")
    else:
        with st.spinner(f"Running pipeline for {episode_yaml} ..."):
            try:
                report = _run(episode_yaml, profile, model_size, out_dir, force)
            except Exception as exc:  # noqa: BLE001 -- surface any pipeline failure to the user
                st.error(f"RUN FAILED: {exc}")
            else:
                run_mod.write_run_report(report, report_path)
                st.session_state["last_episode_yaml"] = str(episode_yaml)
                st.session_state["last_profile"] = profile
                st.session_state["last_model_size"] = model_size
                st.session_state["last_out_dir"] = str(out_dir)
                st.success(f"Run complete: {report_path}")

st.header("Run report")
if report_path.is_file():
    st.markdown(report_path.read_text(encoding="utf-8"))
else:
    st.info(f"No report yet at {report_path}. Run the pipeline first.")

st.header("Plan items")
parts_dir = episode_root / "parts"
if parts_dir.is_dir():
    part_dirs = sorted(p for p in parts_dir.iterdir() if p.is_dir())
    for part_dir in part_dirs:
        plan_path = part_dir / "plan.json"
        if not plan_path.is_file():
            continue
        st.subheader(part_dir.name)
        plan = load_plan(plan_path)
        edited = False
        new_enabled: dict[str, bool] = {}
        for item in plan.items:
            label = f"{item.id} [{item.kind}] {item.start:.2f}s - {item.end:.2f}s -- {item.reason}"
            checked = st.checkbox(label, value=item.enabled, key=f"{part_dir.name}:{item.id}")
            new_enabled[item.id] = checked
            if checked != item.enabled:
                edited = True

        if st.button(f"Save changes to {plan_path.name}", key=f"save:{part_dir.name}", disabled=not edited):
            for item in plan.items:
                item.enabled = new_enabled[item.id]
            save_plan(plan, plan_path)
            st.success(f"Saved {plan_path}")
            st.rerun()
else:
    st.info("No parts directory yet -- run the pipeline first.")

st.header("Apply again")
st.caption(
    "Re-runs the pipeline with the same settings. Caching means only audit/apply "
    "(for parts whose plan.json changed) and assemble actually re-render."
)
if st.button("Apply again"):
    if not episode_yaml.is_file():
        st.error(f"episode.yaml not found: {episode_yaml}")
    else:
        with st.spinner("Re-applying ..."):
            try:
                report = _run(episode_yaml, profile, model_size, out_dir, force=False)
            except Exception as exc:  # noqa: BLE001
                st.error(f"RUN FAILED: {exc}")
            else:
                run_mod.write_run_report(report, report_path)
                st.success(f"Re-applied: {report_path}")
                st.rerun()
