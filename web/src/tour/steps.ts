import type { MessageKey } from "../i18n";

export type TourPlacement = "top" | "bottom" | "left" | "right";

/** Where a step's anchor lives. "any" matches every route (global chrome,
 * e.g. the status bar). "static" is an exact path the tour can navigate to
 * directly. "episode" is a path under the currently known episode id
 * (`/episodes/<id><suffix>`) -- unreachable until an episode id is known. */
export type TourRoute = { kind: "any" } | { kind: "static"; path: string } | { kind: "episode"; suffix: string };

export interface TourStep {
  id: string;
  anchor: string;
  route: TourRoute;
  titleKey: MessageKey;
  bodyKey: MessageKey;
  placement: TourPlacement;
}

export const TOUR_STEPS: TourStep[] = [
  {
    id: "status-bar",
    anchor: "status-bar",
    route: { kind: "any" },
    titleKey: "tour.step.statusBar.title",
    bodyKey: "tour.step.statusBar.body",
    placement: "bottom",
  },
  {
    id: "episodes-list",
    anchor: "episodes-list",
    route: { kind: "static", path: "/episodes" },
    titleKey: "tour.step.episodesList.title",
    bodyKey: "tour.step.episodesList.body",
    placement: "bottom",
  },
  {
    id: "episodes-new",
    anchor: "episodes-new",
    route: { kind: "static", path: "/episodes" },
    titleKey: "tour.step.episodesNew.title",
    bodyKey: "tour.step.episodesNew.body",
    placement: "left",
  },
  {
    id: "wizard-steps",
    anchor: "wizard-steps",
    route: { kind: "static", path: "/episodes/new" },
    titleKey: "tour.step.wizardSteps.title",
    bodyKey: "tour.step.wizardSteps.body",
    placement: "bottom",
  },
  {
    id: "wizard-upload",
    anchor: "wizard-upload",
    route: { kind: "static", path: "/episodes/new" },
    titleKey: "tour.step.wizardUpload.title",
    bodyKey: "tour.step.wizardUpload.body",
    placement: "top",
  },
  {
    id: "run-controls",
    anchor: "run-controls",
    route: { kind: "episode", suffix: "" },
    titleKey: "tour.step.runControls.title",
    bodyKey: "tour.step.runControls.body",
    placement: "bottom",
  },
  {
    id: "stage-grid",
    anchor: "stage-grid",
    route: { kind: "episode", suffix: "" },
    titleKey: "tour.step.stageGrid.title",
    bodyKey: "tour.step.stageGrid.body",
    placement: "top",
  },
  {
    id: "log-panel",
    anchor: "log-panel",
    route: { kind: "episode", suffix: "" },
    titleKey: "tour.step.logPanel.title",
    bodyKey: "tour.step.logPanel.body",
    placement: "top",
  },
  {
    id: "item-list",
    anchor: "item-list",
    route: { kind: "episode", suffix: "/review" },
    titleKey: "tour.step.itemList.title",
    bodyKey: "tour.step.itemList.body",
    placement: "left",
  },
  {
    id: "waveform",
    anchor: "waveform",
    route: { kind: "episode", suffix: "/review" },
    titleKey: "tour.step.waveform.title",
    bodyKey: "tour.step.waveform.body",
    placement: "bottom",
  },
  {
    id: "review-reapply",
    anchor: "review-reapply",
    route: { kind: "episode", suffix: "/review" },
    titleKey: "tour.step.reviewReapply.title",
    bodyKey: "tour.step.reviewReapply.body",
    placement: "bottom",
  },
  {
    id: "clips-generate",
    anchor: "clips-generate",
    route: { kind: "episode", suffix: "/clips" },
    titleKey: "tour.step.clipsGenerate.title",
    bodyKey: "tour.step.clipsGenerate.body",
    placement: "bottom",
  },
  {
    id: "clips-play",
    anchor: "clips-play",
    route: { kind: "episode", suffix: "/clips" },
    titleKey: "tour.step.clipsPlay.title",
    bodyKey: "tour.step.clipsPlay.body",
    placement: "top",
  },
  {
    id: "clips-download",
    anchor: "clips-download",
    route: { kind: "episode", suffix: "/clips" },
    titleKey: "tour.step.clipsDownload.title",
    bodyKey: "tour.step.clipsDownload.body",
    placement: "top",
  },
  {
    id: "deliverables-download",
    anchor: "deliverables-download",
    route: { kind: "episode", suffix: "/deliverables" },
    titleKey: "tour.step.deliverablesDownload.title",
    bodyKey: "tour.step.deliverablesDownload.body",
    placement: "bottom",
  },
  {
    id: "deliverables-report",
    anchor: "deliverables-report",
    route: { kind: "episode", suffix: "/deliverables" },
    titleKey: "tour.step.deliverablesReport.title",
    bodyKey: "tour.step.deliverablesReport.body",
    placement: "top",
  },
];
