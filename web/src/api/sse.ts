import type { JobEventPayload } from "./types";

export type StageRunStatus =
  | "pending"
  | "running"
  | "ran"
  | "cached"
  | "skipped"
  | "failed"
  | "cancelled";

export interface StageInfo {
  status: StageRunStatus;
  elapsed?: number | null;
  updatedAt?: number;
}

export type PartStagesMap = Record<string, StageInfo>;

export interface RunState {
  jobId: string | null;
  status: "idle" | "queued" | "running" | "done" | "failed" | "cancelled";
  error: string | null;
  stages: Record<string, PartStagesMap>; // partStem -> stageName -> StageInfo
  logs: string[];
}

export type RunAction =
  | { type: "RESET"; jobId?: string | null }
  | { type: "CANCEL" }
  | { type: "SSE_EVENT"; payload: JobEventPayload }
  | {
      type: "INIT_STAGES";
      parts: Array<{
        stem: string;
        stages?: Array<{ name: string; status: string; elapsed?: number | null }>;
      }>;
      assemblyStatus?: string;
    };

export const INITIAL_RUN_STATE: RunState = {
  jobId: null,
  status: "idle",
  error: null,
  stages: {},
  logs: [],
};

export const ALL_PART_STAGES = [
  "probe",
  "clean",
  "plan-pauses",
  "transcribe",
  "plan-fillers",
  "audit",
  "apply",
] as const;

export const ALL_PIPELINE_STAGES = [...ALL_PART_STAGES, "assemble"] as const;

export function runStateReducer(state: RunState, action: RunAction): RunState {
  switch (action.type) {
    case "RESET": {
      return {
        ...INITIAL_RUN_STATE,
        jobId: action.jobId ?? null,
      };
    }

    case "INIT_STAGES": {
      const newStages: Record<string, PartStagesMap> = {};
      for (const part of action.parts) {
        newStages[part.stem] = {};
        for (const stage of ALL_PART_STAGES) {
          const existing = part.stages?.find((s) => s.name === stage);
          let status: StageRunStatus = "pending";
          let elapsed: number | null = null;
          if (existing) {
            const rawStatus = existing.status.toLowerCase();
            if (rawStatus === "ran" || rawStatus === "done") status = "ran";
            else if (rawStatus === "cached") status = "cached";
            else if (rawStatus === "skipped") status = "skipped";
            else if (rawStatus === "running") status = "running";
            else if (rawStatus === "failed") status = "failed";
            elapsed = existing.elapsed ?? null;
          }
          newStages[part.stem][stage] = { status, elapsed };
        }
      }

      // Initialize assembly stage
      const assemblyStatusRaw = (action.assemblyStatus || "").toLowerCase();
      let assemblyStatus: StageRunStatus = "pending";
      if (assemblyStatusRaw === "done" || assemblyStatusRaw === "ran") {
        assemblyStatus = "ran";
      } else if (assemblyStatusRaw === "cached") {
        assemblyStatus = "cached";
      } else if (assemblyStatusRaw === "skipped") {
        assemblyStatus = "skipped";
      }
      newStages["__assemble__"] = {
        assemble: { status: assemblyStatus },
      };

      return {
        ...state,
        stages: newStages,
      };
    }

    case "CANCEL": {
      // Set job status to cancelled and any running stages to cancelled
      const updatedStages = { ...state.stages };
      for (const partKey of Object.keys(updatedStages)) {
        const partStages = { ...updatedStages[partKey] };
        for (const stageKey of Object.keys(partStages)) {
          if (partStages[stageKey].status === "running") {
            partStages[stageKey] = {
              ...partStages[stageKey],
              status: "cancelled",
              updatedAt: Date.now(),
            };
          }
        }
        updatedStages[partKey] = partStages;
      }
      return {
        ...state,
        status: "cancelled",
        stages: updatedStages,
      };
    }

    case "SSE_EVENT": {
      const evt = action.payload;
      const eventName = evt.event;

      if (eventName === "job_started") {
        return {
          ...state,
          status: "running",
          error: null,
        };
      }

      if (eventName === "job_finished") {
        return {
          ...state,
          status: "done",
        };
      }

      if (eventName === "job_cancelled") {
        return runStateReducer(state, { type: "CANCEL" });
      }

      if (eventName === "job_failed") {
        const updatedStages = { ...state.stages };
        for (const partKey of Object.keys(updatedStages)) {
          const partStages = { ...updatedStages[partKey] };
          for (const stageKey of Object.keys(partStages)) {
            if (partStages[stageKey].status === "running") {
              partStages[stageKey] = {
                ...partStages[stageKey],
                status: "failed",
                updatedAt: Date.now(),
              };
            }
          }
          updatedStages[partKey] = partStages;
        }
        return {
          ...state,
          status: "failed",
          error: evt.message || "執行失敗",
          stages: updatedStages,
        };
      }

      if (eventName === "log") {
        if (!evt.message) return state;
        const nextLogs = [...state.logs, evt.message];
        if (nextLogs.length > 200) {
          nextLogs.splice(0, nextLogs.length - 200);
        }
        return {
          ...state,
          logs: nextLogs,
        };
      }

      // Stage events: started, finished, cached, skipped
      if (
        eventName === "started" ||
        eventName === "finished" ||
        eventName === "cached" ||
        eventName === "skipped"
      ) {
        const stageName = evt.stage || "";
        const partKey = evt.part || (stageName === "assemble" ? "__assemble__" : "unknown");

        let nextStatus: StageRunStatus = "pending";
        if (eventName === "started") nextStatus = "running";
        else if (eventName === "finished") nextStatus = "ran";
        else if (eventName === "cached") nextStatus = "cached";
        else if (eventName === "skipped") nextStatus = "skipped";

        const currentPartStages = state.stages[partKey] || {};
        const updatedPartStages = {
          ...currentPartStages,
          [stageName]: {
            status: nextStatus,
            elapsed: evt.elapsed !== undefined ? evt.elapsed : currentPartStages[stageName]?.elapsed,
            updatedAt: Date.now(),
          },
        };

        return {
          ...state,
          stages: {
            ...state.stages,
            [partKey]: updatedPartStages,
          },
        };
      }

      return state;
    }

    default:
      return state;
  }
}
