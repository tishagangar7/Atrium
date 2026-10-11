/// <reference lib="webworker" />
import { createWorld, advance, applyIntervention, evaluate } from "./engine";
import type { WorkerCommand, WorkerReply } from "./types";
let world = createWorld();
let playing = false;
let timer: ReturnType<typeof setInterval> | undefined;
function reply(message: WorkerReply) {
  self.postMessage(message);
}
function publish() {
  reply({ type: "snapshot", snapshot: world, playing });
}
function stop() {
  clearInterval(timer);
  timer = undefined;
  playing = false;
}
self.onmessage = (event: MessageEvent<WorkerCommand>) => {
  try {
    const cmd = event.data;
    if (cmd.type === "reset") {
      stop();
      world = createWorld(cmd.seed, cmd.weather);
    } else if (cmd.type === "play") {
      if (![1, 2, 4].includes(cmd.speed))
        throw new Error("Unsupported playback speed");
      stop();
      playing = cmd.playing && !world.completed;
      if (playing)
        timer = setInterval(() => {
          advance(world);
          if (world.completed) stop();
          publish();
        }, 500 / cmd.speed);
    } else if (cmd.type === "step") {
      stop();
      advance(world);
    } else if (cmd.type === "intervene") {
      applyIntervention(world, cmd.intervention, cmd.expectedVersion);
      stop();
    } else if (cmd.type === "evaluate") {
      if (cmd.expectedVersion !== world.state_version)
        throw new Error("Evaluation discarded: stale world");
      reply({
        type: "evaluation",
        requestId: cmd.requestId,
        state_version: world.state_version,
        metrics: evaluate(world, cmd.intervention, cmd.steps),
      });
      return;
    } else throw new Error("Unknown worker command");
    publish();
  } catch (error) {
    reply({
      type: "error",
      message: error instanceof Error ? error.message : "Simulation error",
    });
  }
};
publish();
