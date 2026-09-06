import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createJobEventSource, fetchClips, fetchEpisode, generateClips } from "../api/client";
import type { ClipCandidate, JobStateResponse } from "../api/types";
import { useLocale } from "../i18n";
import { formatCount, formatDecimal, formatMinutesSeconds } from "../lib/format";

const media = (episode: string, path: string) => `/api/media/${encodeURIComponent(episode)}/${path.split(/[\\/]/).map(encodeURIComponent).join("/")}`;
export const ClipsPage: React.FC = () => {
  const { id = "" } = useParams<{ id: string }>(); const queryClient = useQueryClient();
  const { t, locale } = useLocale();
  const fmt = (n: number) => formatMinutesSeconds(n, locale);
  const [part, setPart] = useState(""); const [job, setJob] = useState<JobStateResponse | null>(null); const [message, setMessage] = useState(""); const audioRef = useRef<HTMLAudioElement>(null); const playbackCleanupRef = useRef<(() => void) | null>(null);
  const [loadingClipId, setLoadingClipId] = useState<string | null>(null); const [playError, setPlayError] = useState("");
  const { data: episode } = useQuery({ queryKey: ["episode", id], queryFn: () => fetchEpisode(id) });
  const activePart = part || episode?.parts_detail?.[0]?.stem || episode?.parts?.[0]?.replace(/\.[^/.]+$/, "") || "";
  const { data, isLoading, error } = useQuery({ queryKey: ["clips", id, activePart], queryFn: () => fetchClips(id, activePart), enabled: Boolean(activePart) });
  useEffect(() => { if (!job) return; const cleanup = createJobEventSource(job.id, (event) => { setMessage(event.message || event.event); if (["job_finished", "job_failed", "job_cancelled"].includes(event.event)) { queryClient.invalidateQueries({ queryKey: ["clips", id, activePart] }); setJob(null); } }); return cleanup; }, [job, id, activePart, queryClient]);
  async function generate(render: boolean) { try { setMessage(render ? t("clips.generatingRender") : t("clips.generating")); setJob(await generateClips(id, activePart, render)); } catch (e) { setMessage((e as Error).message); } }
  function play(candidate: ClipCandidate) {
    const audio = audioRef.current; if (!audio) return;
    playbackCleanupRef.current?.();
    setPlayError(""); setLoadingClipId(null);
    const clipId = String(candidate.id);
    const source = media(id, `parts/${activePart}/${activePart}.clean.wav`);
    let stop: (() => void) | null = null;
    const start = () => {
      setLoadingClipId(null);
      audio.currentTime = candidate.start; void audio.play();
      const onTimeUpdate = () => { if (audio.currentTime >= candidate.end) { audio.pause(); stop?.(); } };
      audio.addEventListener("timeupdate", onTimeUpdate);
      stop = () => audio.removeEventListener("timeupdate", onTimeUpdate);
    };
    const onLoadedMetadata = () => { audio.removeEventListener("loadedmetadata", onLoadedMetadata); audio.removeEventListener("error", onLoadError); start(); };
    const onLoadError = () => { audio.removeEventListener("loadedmetadata", onLoadedMetadata); audio.removeEventListener("error", onLoadError); setLoadingClipId(null); setPlayError(t("clips.playError")); };
    if (audio.src !== new URL(source, window.location.href).href) {
      setLoadingClipId(clipId);
      audio.addEventListener("loadedmetadata", onLoadedMetadata);
      audio.addEventListener("error", onLoadError);
      audio.src = source;
    } else {
      start();
    }
    playbackCleanupRef.current = () => { audio.removeEventListener("loadedmetadata", onLoadedMetadata); audio.removeEventListener("error", onLoadError); stop?.(); audio.pause(); };
  }
  useEffect(() => () => { playbackCleanupRef.current?.(); }, []);
  const parts = useMemo(() => episode?.parts_detail?.map((p) => p.stem) || episode?.parts?.map((p) => p.replace(/\.[^/.]+$/, "")) || [], [episode]);
  return <div className="clips-page"><header className="page-header"><div><Link className="dense-btn" to={`/episodes/${id}`}>{t("nav.back")}</Link><h1>{t("clips.heading")} <span className="mono">{t("clips.navTag")}</span></h1></div><div className="clip-actions" data-tour="clips-generate"><button className="dense-btn" onClick={() => generate(false)} disabled={Boolean(job)}>{t("clips.generate")}</button><button className="dense-btn primary" onClick={() => generate(true)} disabled={Boolean(job)}>{t("clips.generateRender")}</button></div></header><div className="clips-toolbar"><label>{t("clips.part")} <select className="dense-select" value={activePart} onChange={(e) => setPart(e.target.value)}>{parts.map((p) => <option key={p} value={p}>{p}</option>)}</select></label><span className="mono">{message || (data ? t("clips.count", { count: formatCount(data.candidates.length, locale) }) : t("clips.notGenerated"))}</span></div>{job && <div className="job-progress"><span className="status-dot blue" />{t("clips.running")}</div>}{isLoading && <div className="empty-box">{t("common.loading")}</div>}{error && <div className="empty-box">{t("clips.notGenerated")}</div>}{!isLoading && !error && data && <div className="clips-table-wrap"><table className="clips-table"><thead><tr><th>{t("clips.rank")}</th><th>{t("clips.window")}</th><th>{t("clips.duration")}</th><th>{t("clips.score")}</th><th>{t("clips.excerpt")}</th><th>{t("clips.actions")}</th></tr></thead><tbody>{data.candidates.map((candidate, index) => <tr key={String(candidate.id)}><td className="mono">{String(index + 1).padStart(2, "0")}</td><td className="mono">{fmt(candidate.start)} → {fmt(candidate.end)}</td><td className="mono">{fmt(candidate.end - candidate.start)}</td><td className="mono" title={candidate.score_components ? Object.entries(candidate.score_components).map(([k, v]) => `${k}: ${v}`).join("\n") : ""}>{formatDecimal(candidate.score, locale, 2)}</td><td className="excerpt">{candidate.text}</td><td><div className="row-actions"><button className="dense-btn" data-tour={index === 0 ? "clips-play" : undefined} onClick={() => play(candidate)} disabled={loadingClipId === String(candidate.id)}>{loadingClipId === String(candidate.id) ? t("clips.loadingAudio") : t("common.play")}</button>{(candidate.rendered?.mp3 || candidate.rendered?.srt) && <span data-tour={index === 0 ? "clips-download" : undefined} style={{ display: "inline-flex", gap: "4px" }}>{candidate.rendered?.mp3 && <a className="dense-btn" href={candidate.rendered.mp3} download>MP3</a>}{candidate.rendered?.srt && <a className="dense-btn" href={candidate.rendered.srt} download>SRT</a>}</span>}</div></td></tr>)}</tbody></table></div>}{playError && <div className="inline-error">{playError}</div>}<audio ref={audioRef} controls className="clip-audio" /></div>;
};
