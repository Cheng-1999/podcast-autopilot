import React, { useEffect, useRef } from "react";
import { Routes, Route, Navigate, useNavigate, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchHealth, fetchEpisodes } from "./api/client";
import { StatusBar } from "./components/StatusBar";
import { EpisodesPage } from "./pages/EpisodesPage";
import { EpisodeDetailPage } from "./pages/EpisodeDetailPage";
import { NewEpisodePage } from "./pages/NewEpisodePage";
import { ClipsPage } from "./pages/ClipsPage";
import { ReviewPage } from "./pages/ReviewPage";
import { DeliverablesPage } from "./pages/DeliverablesPage";
import type { EpisodeSummary } from "./api/types";

export const App: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();

  // Fetch health data for top status bar
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 10000,
  });

  // Query episodes to find active job if any
  const { data: episodes } = useQuery<EpisodeSummary[]>({
    queryKey: ["episodes"],
    queryFn: fetchEpisodes,
    refetchInterval: 5000,
  });

  const activeEpisode = episodes?.find((e) => e.status === "running" && e.job_id);
  const activeJob = activeEpisode
    ? {
        id: activeEpisode.job_id!,
        episodeId: activeEpisode.id,
        status: "running",
        startedAt: activeEpisode.last_run_time,
      }
    : null;

  // Global keyboard sequence handler: "g" followed by "e" -> navigate to /episodes
  const lastKeyRef = useRef<{ key: string; time: number }>({ key: "", time: 0 });

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.target instanceof HTMLSelectElement
      ) {
        return;
      }

      const now = Date.now();
      const prev = lastKeyRef.current;

      if (prev.key === "g" && e.key === "e" && now - prev.time < 1000) {
        e.preventDefault();
        lastKeyRef.current = { key: "", time: 0 };
        if (location.pathname !== "/episodes") {
          navigate("/episodes");
        }
        return;
      }

      lastKeyRef.current = { key: e.key.toLowerCase(), time: now };
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [navigate, location.pathname]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        minHeight: "100vh",
        backgroundColor: "var(--surface-bg)",
      }}
    >
      <StatusBar health={health} activeJob={activeJob} />

      <main
        style={{
          flex: 1,
          padding: "16px",
          maxWidth: "1440px",
          width: "100%",
          margin: "0 auto",
          boxSizing: "border-box",
        }}
      >
        <Routes>
          <Route path="/" element={<Navigate to="/episodes" replace />} />
          <Route path="/episodes" element={<EpisodesPage />} />
          <Route path="/episodes/new" element={<NewEpisodePage />} />
          <Route path="/episodes/:id" element={<EpisodeDetailPage />} />
          <Route path="/episodes/:id/review" element={<ReviewPage />} />
          <Route path="/episodes/:id/clips" element={<ClipsPage />} />
          <Route path="/episodes/:id/deliverables" element={<DeliverablesPage />} />
          <Route path="*" element={<Navigate to="/episodes" replace />} />
        </Routes>
      </main>
    </div>
  );
};
