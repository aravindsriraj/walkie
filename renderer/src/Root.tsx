import React from "react";
import { Composition } from "remotion";
import { FPS, OUT_W, StepClip, type StepClipProps } from "./StepClip";

const even = (n: number) => Math.round(n / 2) * 2;

export const Root: React.FC = () => (
  <Composition
    id="StepClip"
    component={StepClip}
    fps={FPS}
    width={OUT_W}
    height={800}
    durationInFrames={90}
    defaultProps={{
      src: "",
      startMs: 0,
      endMs: 3000,
      clickMs: 1500,
      rect: null,
      zoom: { x: 0, y: 0, w: 1280, h: 800 },
      redact: [],
      videoW: 1280,
      videoH: 800,
    } satisfies StepClipProps}
    calculateMetadata={({ props }) => ({
      durationInFrames: Math.max(1, Math.round(((props.endMs - props.startMs) / 1000) * FPS)),
      height: even((OUT_W * props.videoH) / props.videoW),
    })}
  />
);
