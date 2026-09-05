import React, { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { createEpisode, fetchEpisodes, registerLocalPath, runEpisode, uploadFile } from "../api/client";
import { reorder, validateChapters } from "../api/validation";
import type { EpisodeCreateBody, UploadResponse } from "../api/types";
import { useLocale } from "../i18n";

type Part = UploadResponse & { name: string; progress: number; path: string };
type Chapter = { start: string; title: string };
const emptyTags = { artist: "", album: "", year: "", comment: "" };

function formatDuration(seconds: number) { return `${Math.floor(seconds / 60)}:${Math.floor(seconds % 60).toString().padStart(2, "0")}`; }
function UploadDrop({ onFiles, label }: { onFiles: (files: File[]) => void; label: string }) {
  const [drag, setDrag] = useState(false);
  return <label className={`upload-drop${drag ? " is-dragging" : ""}`} onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={(e) => { e.preventDefault(); setDrag(false); onFiles(Array.from(e.dataTransfer.files)); }}>
    <input type="file" accept=".wav,.mp3,.flac,.m4a,audio/*" multiple onChange={(e) => onFiles(Array.from(e.target.files || []))} />
    <span className="mono">＋</span><span>{label}</span><small>WAV / MP3 / FLAC / M4A</small>
  </label>;
}

export const NewEpisodePage: React.FC = () => {
  const { t } = useLocale();
  const navigate = useNavigate();
  const { data: episodes } = useQuery({ queryKey: ["episodes"], queryFn: fetchEpisodes });
  const latest = useMemo(() => [...(episodes || [])].sort((a, b) => (b.last_run_time || 0) - (a.last_run_time || 0))[0], [episodes]);
  const [step, setStep] = useState(1);
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
    setError(""); if (!title.trim() || !parts.length) { setError("Please enter a title and add at least one part audio file"); return; }
    const chapterError = validateChapters(chapters.filter((c) => c.title || c.start), totalDuration); if (chapterError) { setStep(3); setError(chapterError); return; }
    setSaving(true); try { const body: EpisodeCreateBody = { title: title.trim(), episode, parts: parts.map((p) => p.path), intro: intro?.path || null, outro: outro?.path || null, bgm: bgm ? { path: bgm.path, gain_db: Number(duck.gain_db), duck: Object.fromEntries(Object.entries(duck).filter(([key]) => key !== "gain_db").map(([k, v]) => [k, Number(v)])) } : null, chapters: chapters.filter((c) => c.title || c.start), tags: { ...tags, year: tags.year ? Number(tags.year) : null } }; const created = await createEpisode(body); if (runNow) await runEpisode(created.id, { profile: "default", model: "medium", force: false, skip: [] }); navigate(`/episodes/${created.id}`); } catch (e) { setError((e as Error).message); } finally { setSaving(false); }
  }
  const field = (label: string, value: string, set: (value: string) => void, type = "text") => <label className="wizard-field"><span>{label}</span><input className="dense-input" type={type} value={value} onChange={(e) => set(e.target.value)} /></label>;
  return <div className="wizard-page">
    <header className="page-header"><div><button className="dense-btn" onClick={() => navigate("/episodes")}>{t("nav.list")}</button><h1>{t("new.heading")} <span className="mono">/ NEW EPISODE</span></h1></div><span className="mono wizard-counter">STEP {step} / 3</span></header>
    <nav className="wizard-steps">{["基本資料", "段落音檔", "配樂與章節"].map((name, i) => <button key={name} className={step === i + 1 ? "active" : step > i + 1 ? "complete" : ""} onClick={() => setStep(i + 1)}><b>{String(i + 1).padStart(2, "0")}</b>{name}</button>)}</nav>
    {error && <div className="inline-error">{error}</div>}
    {step === 1 && <section className="wizard-panel"><h2>基本資料 <small>沿用最近集數的標籤作為起點</small></h2><div className="form-grid">{field("標題 TITLE", title, setTitle)}{field("集數 EPISODE", String(episode), (v) => setEpisode(Number(v) || 0), "number")}{field("藝術家 ARTIST", tags.artist, (v) => setTags({ ...tags, artist: v }))}{field("專輯 ALBUM", tags.album, (v) => setTags({ ...tags, album: v }))}{field("年份 YEAR", tags.year, (v) => setTags({ ...tags, year: v }), "number")}<label className="wizard-field wide"><span>備註 COMMENT</span><input className="dense-input" value={tags.comment} onChange={(e) => setTags({ ...tags, comment: e.target.value })} /></label></div><div className="wizard-actions"><button className="dense-btn primary" onClick={() => setStep(2)}>下一步：加入段落 →</button></div></section>}
    {step === 2 && <section className="wizard-panel"><h2>段落音檔 <small>{parts.length} 個檔案 · {formatDuration(totalDuration)} · 可重新排序</small></h2><UploadDrop label="拖曳段落音檔至此，或點擊選取" onFiles={(files) => addFiles(files)} /><div className="path-row"><input className="dense-input" placeholder="貼上本機絕對路徑，例如 C:\\audio\\part-01.wav" value={localPath} onChange={(e) => setLocalPath(e.target.value)} /><button className="dense-btn" onClick={addPath}>註冊路徑</button></div><div className="upload-list">{parts.map((part, index) => <div className="upload-row" key={`${part.path}-${index}`}><span className="mono order">{String(index + 1).padStart(2, "0")}</span><span className="file-name">{part.name}<small>{formatDuration(part.duration)} · {part.sr} Hz · {part.channels} ch</small></span><span className="progress"><i style={{ width: `${part.progress * 100}%` }} /></span><button className="dense-btn" disabled={index === 0} onClick={() => movePart(index, -1)}>↑</button><button className="dense-btn" disabled={index === parts.length - 1} onClick={() => movePart(index, 1)}>↓</button></div>)}</div><div className="wizard-actions"><button className="dense-btn" onClick={() => setStep(1)}>← 上一步</button><button className="dense-btn primary" disabled={!parts.length} onClick={() => setStep(3)}>下一步：配樂與章節 →</button></div></section>}
    {step === 3 && <section className="wizard-panel"><h2>配樂與章節 <small>全部為選填</small></h2><div className="asset-grid">{([["intro", "Intro", intro, setIntro], ["outro", "Outro", outro, setOutro], ["bgm", "BGM", bgm, setBgm]] as const).map(([key, name, value]) => <div className="asset-box" key={key}><div className="asset-heading"><b>{name}</b><span>{value?.name || "尚未加入"}</span></div><UploadDrop label={`加入 ${name} 音檔`} onFiles={(files) => addFiles(files, key as "intro" | "outro" | "bgm")} />{key === "bgm" && <div className="duck-grid">{field("GAIN dB", duck.gain_db, (v) => setDuck({ ...duck, gain_db: v }), "number")}{field("THRESHOLD", duck.threshold, (v) => setDuck({ ...duck, threshold: v }))}{field("RATIO", duck.ratio, (v) => setDuck({ ...duck, ratio: v }))}{field("ATTACK ms", duck.attack, (v) => setDuck({ ...duck, attack: v }))}{field("RELEASE ms", duck.release, (v) => setDuck({ ...duck, release: v }))}</div>}</div>)}</div><div className="chapter-heading"><h3>章節 CHAPTERS</h3><span className="mono">總長 {formatDuration(totalDuration)}</span></div><div className="chapter-list">{chapters.map((chapter, index) => <div className="chapter-row" key={index}><span className="mono">{String(index + 1).padStart(2, "0")}</span><input className="dense-input chapter-time" placeholder="mm:ss" value={chapter.start} onChange={(e) => updateChapter(index, "start", e.target.value)} /><input className="dense-input" placeholder="章節標題" value={chapter.title} onChange={(e) => updateChapter(index, "title", e.target.value)} /><button className="dense-btn" onClick={() => setChapters((old) => old.filter((_, i) => i !== index))}>移除</button></div>)}</div><button className="dense-btn" onClick={() => setChapters((old) => [...old, { start: "", title: "" }])}>＋ 新增章節</button><div className="wizard-actions"><button className="dense-btn" onClick={() => setStep(2)}>← 上一步</button><button className="dense-btn" disabled={saving} onClick={() => submit(false)}>建立集數</button><button className="dense-btn primary" disabled={saving} onClick={() => submit(true)}>{saving ? "建立中..." : "建立並立即執行 →"}</button></div></section>}
  </div>;
};
