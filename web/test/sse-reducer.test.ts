import { describe, it, expect } from "vitest";
import {
  runStateReducer,
  INITIAL_RUN_STATE,
  type RunState,
} from "../src/api/sse";

describe("runStateReducer", () => {
  it("initializes stages correctly", () => {
    const state = runStateReducer(INITIAL_RUN_STATE, {
      type: "INIT_STAGES",
      parts: [
        {
          stem: "part1",
          stages: [{ name: "probe", status: "ran", elapsed: 0.8 }],
        },
      ],
      assemblyStatus: "done",
    });

    expect(state.stages["part1"]["probe"]).toEqual({
      status: "ran",
      elapsed: 0.8,
    });
    expect(state.stages["part1"]["clean"]).toEqual({
      status: "pending",
      elapsed: null,
    });
    expect(state.stages["__assemble__"]["assemble"]).toEqual({
      status: "ran",
    });
  });

  it("handles started -> running", () => {
    const startEvent = {
      seq: 1,
      event: "started",
      stage: "probe",
      part: "part1",
    };

    const state = runStateReducer(INITIAL_RUN_STATE, {
      type: "SSE_EVENT",
      payload: startEvent,
    });

    expect(state.stages["part1"]["probe"].status).toBe("running");
  });

  it("handles finished -> ran with elapsed", () => {
    // First start
    let state = runStateReducer(INITIAL_RUN_STATE, {
      type: "SSE_EVENT",
      payload: { seq: 1, event: "started", stage: "clean", part: "part1" },
    });
    expect(state.stages["part1"]["clean"].status).toBe("running");

    // Then finish with elapsed
    state = runStateReducer(state, {
      type: "SSE_EVENT",
      payload: {
        seq: 2,
        event: "finished",
        stage: "clean",
        part: "part1",
        elapsed: 4.25,
      },
    });

    expect(state.stages["part1"]["clean"].status).toBe("ran");
    expect(state.stages["part1"]["clean"].elapsed).toBe(4.25);
  });

  it("handles cached", () => {
    const state = runStateReducer(INITIAL_RUN_STATE, {
      type: "SSE_EVENT",
      payload: { seq: 3, event: "cached", stage: "transcribe", part: "part1" },
    });

    expect(state.stages["part1"]["transcribe"].status).toBe("cached");
  });

  it("handles cancel action and flips running stages to cancelled", () => {
    let state = runStateReducer(INITIAL_RUN_STATE, {
      type: "SSE_EVENT",
      payload: { seq: 1, event: "job_started" },
    });
    state = runStateReducer(state, {
      type: "SSE_EVENT",
      payload: { seq: 2, event: "started", stage: "transcribe", part: "part1" },
    });
    expect(state.status).toBe("running");
    expect(state.stages["part1"]["transcribe"].status).toBe("running");

    // Cancel triggered
    state = runStateReducer(state, { type: "CANCEL" });

    expect(state.status).toBe("cancelled");
    expect(state.stages["part1"]["transcribe"].status).toBe("cancelled");
  });

  it("handles job_cancelled SSE event", () => {
    let state = runStateReducer(INITIAL_RUN_STATE, {
      type: "SSE_EVENT",
      payload: { seq: 1, event: "started", stage: "apply", part: "part1" },
    });
    state = runStateReducer(state, {
      type: "SSE_EVENT",
      payload: { seq: 2, event: "job_cancelled" },
    });

    expect(state.status).toBe("cancelled");
    expect(state.stages["part1"]["apply"].status).toBe("cancelled");
  });

  it("maintains at most 200 log entries", () => {
    let state: RunState = INITIAL_RUN_STATE;
    for (let i = 0; i < 250; i++) {
      state = runStateReducer(state, {
        type: "SSE_EVENT",
        payload: { seq: i, event: "log", message: `Log line ${i}` },
      });
    }

    expect(state.logs.length).toBe(200);
    expect(state.logs[0]).toBe("Log line 50");
    expect(state.logs[199]).toBe("Log line 249");
  });
});
