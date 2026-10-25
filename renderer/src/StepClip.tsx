import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  OffthreadVideo,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

type Box = { x: number; y: number; w: number; h: number };
type Redaction = { fromMs: number; toMs: number; rects: Box[] };

export type StepClipProps = {
  src: string;
  startMs: number;
  endMs: number;
  clickMs: number;
  rect: Box | null;
  zoom: Box;
  redact: Redaction[];
  videoW: number;
  videoH: number;
};

export const FPS = 30;
export const OUT_W = 1280;

const ease = Easing.bezier(0.4, 0, 0.2, 1);

export const StepClip: React.FC<StepClipProps> = ({ src, startMs, clickMs, rect, zoom, redact, videoW }) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();
  const k = width / videoW; // source px → output px
  const clickFrame = ((clickMs - startMs) / 1000) * FPS;

  // Hold the full frame, then ease into the zoom box and hold.
  const p = interpolate(frame, [8, 26], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  // Camera box eases from the full frame to the zoom box; the transform maps it onto the output.
  const camX = interpolate(p, [0, 1], [0, zoom.x]);
  const camY = interpolate(p, [0, 1], [0, zoom.y]);
  const camW = interpolate(p, [0, 1], [videoW, zoom.w]);
  const scale = videoW / camW;
  const tx = -camX * k * scale;
  const ty = -camY * k * scale;

  const spot = interpolate(frame, [22, 32], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const ripple = interpolate(frame, [clickFrame, clickFrame + 12], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const pad = 6;
  const nowMs = startMs + (frame / FPS) * 1000;
  const blurred = redact.filter((r) => nowMs >= r.fromMs && nowMs < r.toMs).flatMap((r) => r.rects);

  return (
    <AbsoluteFill style={{ backgroundColor: "#111" }}>
      <AbsoluteFill style={{ transform: `translate(${tx}px, ${ty}px) scale(${scale})`, transformOrigin: "0 0" }}>
        <OffthreadVideo src={src} trimBefore={Math.round((startMs / 1000) * FPS)} muted />
        {blurred.map((b, i) => (
          <div
            key={i}
            style={{
              position: "absolute", left: b.x * k, top: b.y * k, width: b.w * k, height: b.h * k,
              backdropFilter: "blur(10px)", background: "rgba(229, 231, 235, 0.55)", borderRadius: 4,
            }}
          />
        ))}
        {rect && (
          <div
            style={{
              position: "absolute",
              left: (rect.x - pad) * k,
              top: (rect.y - pad) * k,
              width: (rect.w + pad * 2) * k,
              height: (rect.h + pad * 2) * k,
              borderRadius: 8,
              border: `${3 / scale}px solid rgba(109, 40, 217, ${spot})`,
              boxShadow: `0 0 0 9999px rgba(0, 0, 0, ${0.45 * spot})`,
            }}
          />
        )}
        {rect && ripple > 0 && ripple < 1 && (
          <div
            style={{
              position: "absolute",
              left: (rect.x + rect.w / 2) * k - 30,
              top: (rect.y + rect.h / 2) * k - 30,
              width: 60,
              height: 60,
              borderRadius: "50%",
              background: "rgba(109, 40, 217, 0.6)",
              opacity: 1 - ripple,
              transform: `scale(${0.3 + ripple * 1.2})`,
            }}
          />
        )}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
