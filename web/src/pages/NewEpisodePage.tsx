import React, { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { createEpisode, fetchEpisodes, registerLocalPath, runEpisode, uploadFile } from "../api/client";
import { reorder, validateChapters } from "../api/validation";
import type { EpisodeCreateBody, UploadResponse } from "../api/types";
import { useLocale } from "../i18n";
import { formatCount, formatMinutesSeconds } from "../lib/format";
import { useTourOptional } from "../tour/context";

type Part = UploadResponse & { name: string; progress: number; path: string };
type Chapter = { start: string; title: string };
const emptyTags = { artist: "", album: "", year: "", comment: "" };
function UploadDrop({ onFiles, label, tourAnchor }: { onFiles: (files: File[]) => void; label: string; tourAnchor?: string }) {
  const [drag, setDrag] = useState(false);
  return <label data-tour={tourAnchor} className={`upload-drop${drag ? " is-dragging" : ""}`} onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={(e) => { e.preventDefault(); setDrag(false); onFiles(Array.from(e.dataTransfer.files)); }}>
    <input type="file" accept=".wav,.mp3,.flac,.m4a,audio/*" multiple onChange={(e) => onFiles(Array.from(e.target.files || []))} />
    <span className="mono">＋</span><span>{label}</span><small>WAV / MP3 / FLAC / M4A</small>
  </label>;
}

export const NewEpisodePage: React.FC = () => {
  const { t, locale } = useLocale();
  const navigate = useNavigate();
  const { data: episodes } = useQuery({ queryKey: ["episodes"], queryFn: fetchEpisodes });
  const latest = useMemo(() => [...(episodes || [])].sort((a, b) => (b.last_run_time || 0) - (a.last_run_time || 0))[0], [episodes]);
  const [step, setStep] = useState(1);
  const tour = useTourOptional();
  const tourAnchor = tour?.isActive ? tour.step?.anchor : null;
  React.useEffect(() => {
    if (tourAnchor === "wizard-upload") setStep(2);
  }, [tourAnchor]);
  const [title, setTitle] = useState(""); const [episode, setEpisode] = useState(1);
  const [tags, setTags] = useState<Record<string, string>>(() => ({ ...emptyTags }));
  const [parts, setParts] = useState<Part[]>([]); const [localPath, setLocalPath] = useState("");
  const [intro, setIntro] = useState<Part | null>(null); const [outro, setOutro] = useState<Part | null>(null); const [bgm, setBgm] = useState<Part | null>(null);
  const [duck, setDuck] = useState({ gain_db: "-18", threshold: "0.03", ratio: "8", attack: "5", release: "300" });
  const [chapters, setChapters] = useState<Chapter[]>([{ start: "00:00", title: "" }]);
  const [error, setError] = useState(""); const [saving, setSaving] = useState(false);
  const totalDuration = parts.reduce((sum, part) => sum + (part.duration || 0), 0);

  React.useEffect(() => { if (latest) { const source = latest.tags || {}; setTags({ artist: String(source.artist || ""), album: String(source.album || ""), year: source.year == null ? "" : String(source.year), comment: String(source.comment || "") }); setEpisode((latest.episode || 0) + 1); } }, [latest]);
  async function addFiles(files: File[], target: "parts" | "intro" | "outro" | "bgm" = "parts") {
    setError(""); for (const file of files) { try { const result = await uploadFile(file, title || "_uploads", (progress) => { if (target === "parts") setParts((old) => old.map((p) => p.name === file.name ? { ...p, progress } : p)); }); const item = { ...result, name: file.name, progress: 1 }; if (target === "parts") setParts((old) => [...old.filter((p) => p.name !== file.name), item]); else if (target === "intro") setIntro(item); else if (target === "outro") setOutro(item); else setBgm(item); } catch (e) { setError((e as Error).message); } }
  }
  async function addPath() { if (!localPath.trim()) return; try { const result = await registerLocalPath(localPath.trim()); setParts((old) => [...old, { ...result, name: localPath.split(/[\\/]/).pop() || localPath, progress: 1 }]); setLocalPath(""); } catch (e) { setError((e as Error).message); } }
  function movePart(index: number, direction: -1 | 1) { setParts((old) => reorder(old, index, direction)); }
  function updateChapter(index: number, key: keyof Chapter, value: string) { setChapters((old) => old.map((c, i) => i === index ? { ...c, [key]: value } : c)); }
  async function submit(runNow: boolean) {
    setError(""); if (!title.trim() || !parts.length) { setError(t("new.validationRequired")); return; }
    const chapterError = validateChapters(chapters.filter((c) => c.title || c.start), totalDuration); if (chapterError) { setStep(3); setError(t(chapterError.key, chapterError.params)); return; }
    setSaving(true); try { const body: EpisodeCreateBody = { title: title.trim(), episode, parts: parts.map((p) => p.path), intro: intro?.path || null, outro: outro?.path || null, bgm: bgm ? { path: bgm.path, gain_db: Number(duck.gain_db), duck: Object.fromEntries(Object.entries(duck).filter(([key]) => key !== "gain_db").map(([k, v]) => [k, Number(v)])) } : null, chapters: chapters.filter((c) => c.title || c.start), tags: { ...tags, year: tags.year ? Number(tags.year) : null } }; const created = await createEpisode(body); if (runNow) await runEpisode(created.id, { profile: "default", model: "medium", force: false, skip: [] }); navigate(`/episodes/${created.id}`); } catch (e) { setError((e as Error).message); } finally { setSaving(false); }
  }
  const field = (label: string, value: string, set: (value: string) => void, type = "text") => <label className="wizard-field"><span>{label}</span><input className="dense-input" type={type} value={value} onChange={(e) => set(e.target.value)} /></label>;
  return <div className="wizard-page">
    <header className="page-header"><div><button className="dense-btn" onClick={() => navigate("/episodes")}>{t("nav.list")}</button><h1>{t("new.heading")} <span className="mono">{t("new.navTag")}</span></h1></div><span className="mono wizard-counter">{t("new.step")} {step} / 3</span></header>
    <nav className="wizard-steps" data-tour="wizard-steps">{[t("new.basic"), t("new.parts"), t("new.assets")].map((name, i) => <button key={name} className={step === i + 1 ? "active" : step > i + 1 ? "complete" : ""} onClick={() => setStep(i + 1)}><b>{String(i + 1).padStart(2, "0")}</b>{name}</button>)}</nav>
    {error && <div className="inline-error">{error}</div>}
    {step === 1 && <section className="wizard-panel"><h2>{t("new.basic")} <small>{t("new.basicHint")}</small></h2><div className="form-grid">{field(t("new.title"), title, setTitle)}{field(t("new.episode"), String(episode), (v) => setEpisode(Number(v) || 0), "number")}{field(t("new.artist"), tags.artist, (v) => setTags({ ...tags, artist: v }))}{field(t("new.album"), tags.album, (v) => setTags({ ...tags, album: v }))}{field(t("new.year"), tags.year, (v) => setTags({ ...tags, year: v }), "number")}<label className="wizard-field wide"><span>{t("new.comment")}</span><input className="dense-input" value={tags.comment} onChange={(e) => setTags({ ...tags, comment: e.target.value })} /></label></div><div className="wizard-actions"><button className="dense-btn primary" onClick={() => setStep(2)}>{t("new.nextParts")}</button></div></section>}
    {step === 2 && <section className="wizard-panel"><h2>{t("new.partsHeading")} <small>{t("new.partsHint", { count: formatCount(parts.length, locale), duration: formatMinutesSeconds(totalDuration, locale) })}</small></h2><UploadDrop label={t("new.dropAudio")} onFiles={(files) => addFiles(files)} tourAnchor="wizard-upload" /><div className="path-row"><input className="dense-input" placeholder={t("new.pathPlaceholder")} value={localPath} onChange={(e) => setLocalPath(e.target.value)} /><button className="dense-btn" onClick={addPath}>{t("new.registerPath")}</button></div><div className="upload-list">{parts.map((part, index) => <div className="upload-row" key={`${part.path}-${index}`}><span className="mono order">{String(index + 1).padStart(2, "0")}</span><span className="file-name">{part.name}<small>{formatMinutesSeconds(part.duration, locale)} · {formatCount(part.sr, locale)} Hz · {formatCount(part.channels, locale)} ch</small></span><span className="progress"><i style={{ width: `${part.progress * 100}%` }} /></span><button aria-label={t("common.previous")} className="dense-btn" disabled={index === 0} onClick={() => movePart(index, -1)}>↑</button><button aria-label={t("common.next")} className="dense-btn" disabled={index === parts.length - 1} onClick={() => movePart(index, 1)}>↓</button></div>)}</div><div className="wizard-actions"><button className="dense-btn" onClick={() => setStep(1)}>{t("common.previous")}</button><button className="dense-btn primary" disabled={!parts.length} onClick={() => setStep(3)}>{t("new.nextAssets")}</button></div></section>}
    {step === 3 && <section className="wizard-panel"><h2>{t("new.assetsHeading")} <small>{t("new.optional")}</small></h2><div className="asset-grid">{([["intro", t("new.assetIntro"), intro, setIntro], ["outro", t("new.assetOutro"), outro, setOutro], ["bgm", t("new.assetBgm"), bgm, setBgm]] as const).map(([key, name, value]) => <div className="asset-box" key={key}><div className="asset-heading"><b>{name}</b><span>{value?.name || t("new.notAdded")}</span></div><UploadDrop label={t("new.addAsset", { name })} onFiles={(files) => addFiles(files, key as "intro" | "outro" | "bgm")} />{key === "bgm" && <div className="duck-grid">{field(t("new.gain"), duck.gain_db, (v) => setDuck({ ...duck, gain_db: v }), "number")}{field(t("new.threshold"), duck.threshold, (v) => setDuck({ ...duck, threshold: v }))}{field(t("new.ratio"), duck.ratio, (v) => setDuck({ ...duck, ratio: v }))}{field(t("new.attack"), duck.attack, (v) => setDuck({ ...duck, attack: v }))}{field(t("new.release"), duck.release, (v) => setDuck({ ...duck, release: v }))}</div>}</div>)}</div><div className="chapter-heading"><h3>{t("new.chapterHeading")}</h3><span className="mono">{t("new.totalDuration", { duration: formatMinutesSeconds(totalDuration, locale) })}</span></div><div className="chapter-list">{chapters.map((chapter, index) => <div className="chapter-row" key={index}><span className="mono">{String(index + 1).padStart(2, "0")}</span><input className="dense-input chapter-time" placeholder={t("new.chapterTime")} value={chapter.start} onChange={(e) => updateChapter(index, "start", e.target.value)} /><input className="dense-input" placeholder={t("new.chapterTitle")} value={chapter.title} onChange={(e) => updateChapter(index, "title", e.target.value)} /><button className="dense-btn" onClick={() => setChapters((old) => old.filter((_, i) => i !== index))}>{t("common.remove")}</button></div>)}</div><button className="dense-btn" onClick={() => setChapters((old) => [...old, { start: "", title: "" }])}>{t("new.addChapter")}</button><div className="wizard-actions"><button className="dense-btn" onClick={() => setStep(2)}>{t("common.previous")}</button><button className="dense-btn" disabled={saving} onClick={() => submit(false)}>{t("new.create")}</button><button className="dense-btn primary" disabled={saving} onClick={() => submit(true)}>{saving ? t("new.creating") : t("new.createRun")}</button></div></section>}
  </div>;
};
