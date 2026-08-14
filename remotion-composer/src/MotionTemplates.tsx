import {
  AbsoluteFill,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

// ---------------------------------------------------------------------------
// Motion templates: a CLOSED set of two overlays for vertical (9:16) video.
//
// Both templates play the source clip full bleed and draw one line of the
// operator's own text over a window of it. Nothing here generates copy, picks
// a template, or invents a third one: the caller names the template and hands
// over the text, and these two are all there is.
//
// 9:16 safe by construction. Every size and inset is a fraction of the frame
// the render is running at, so the same component reads the same at 720x1280
// and at 1080x1920, and the text sits inside an 8 percent margin on every
// side rather than at a pixel offset tuned for one resolution.
//
// System fonts only. No font is fetched at render time (no
// @remotion/google-fonts here on purpose), so a render never depends on the
// network and never stalls on a font server.
// ---------------------------------------------------------------------------

// Bundled with Windows and macOS respectively, then the generic fallbacks.
// A missing family falls through to the next name rather than to a download.
const FONT_STACK =
  '"Segoe UI", "Helvetica Neue", Helvetica, Arial, sans-serif';
// Fraction of the frame kept clear on every side.
const SAFE_MARGIN = 0.08;
const DEFAULT_ACCENT = "#22D3EE";

export interface MotionTemplateProps {
  [key: string]: unknown;
  // The clip this overlay is drawn on. Relative paths are read from public/.
  videoSrc: string;
  // The one line of operator text this template shows.
  text: string;
  // The window the overlay occupies, in seconds from the start of the clip.
  inSeconds: number;
  outSeconds: number;
  accentColor?: string;
}

// Resolve asset path: URLs, absolute paths, and public/ relative paths.
// Mirrors the helper in TitledVideo.tsx and Explainer.tsx so an absolute
// Windows or Unix path works as well as a file dropped in public/.
function resolveAsset(src: string): string {
  if (
    src.startsWith("http://") ||
    src.startsWith("https://") ||
    src.startsWith("data:")
  ) {
    return src;
  }
  const clean = src.replace(/^file:\/\/\/?/, "");
  if (clean.startsWith("/") || /^[A-Za-z]:[\\/]/.test(clean)) {
    return `file:///${clean.replace(/\\/g, "/")}`;
  }
  return staticFile(clean);
}

// ---------------------------------------------------------------------------
// hook-title: an animated title over the opening of the clip.
// Words rise into place one after another under a soft top scrim, and an
// accent rule draws in beneath them.
// ---------------------------------------------------------------------------
const HookTitleOverlay: React.FC<{ text: string; accentColor: string }> = ({
  text,
  accentColor,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();

  const words = text.split(/\s+/).filter(Boolean);
  const fontSize = Math.round(width * 0.075);
  const inset = Math.round(width * SAFE_MARGIN);

  // Hold the title, then ease it out over the last third of a second.
  const fadeOut = interpolate(
    frame,
    [Math.max(0, durationInFrames - 10), Math.max(1, durationInFrames - 2)],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  // The rule sweeps in after the first words have landed.
  const rule = spring({
    frame: frame - 10,
    fps,
    config: { damping: 18, stiffness: 70 },
  });

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {/* Scrim so bright type reads over bright footage, top only. */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(to bottom, rgba(0,0,0,0.62) 0%, rgba(0,0,0,0.30) 30%, rgba(0,0,0,0) 52%)",
          opacity: fadeOut,
        }}
      />
      <div
        style={{
          position: "absolute",
          top: Math.round(height * 0.13),
          left: inset,
          right: inset,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          opacity: fadeOut,
        }}
      >
        <div
          style={{
            fontFamily: FONT_STACK,
            fontWeight: 800,
            fontSize,
            lineHeight: 1.12,
            letterSpacing: "-0.01em",
            color: "#FFFFFF",
            textAlign: "center",
            textShadow: "0 2px 0 rgba(0,0,0,0.45), 0 8px 26px rgba(0,0,0,0.55)",
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "center",
            gap: `0 ${Math.round(fontSize * 0.28)}px`,
          }}
        >
          {words.map((word, i) => {
            const wordSpring = spring({
              frame: frame - i * 3,
              fps,
              config: { damping: 14, stiffness: 130 },
            });
            return (
              <span
                key={`${word}-${i}`}
                style={{
                  display: "inline-block",
                  opacity: wordSpring,
                  transform: `translateY(${interpolate(
                    wordSpring,
                    [0, 1],
                    [Math.round(fontSize * 0.45), 0]
                  )}px)`,
                }}
              >
                {word}
              </span>
            );
          })}
        </div>
        <div
          style={{
            marginTop: Math.round(fontSize * 0.34),
            height: Math.max(3, Math.round(fontSize * 0.06)),
            width: `${Math.round(rule * 62)}%`,
            background: accentColor,
            borderRadius: 999,
          }}
        />
      </div>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// cta-endcard: one call to action over the closing seconds.
// Brand free on purpose: no logo, no handle, no mark, just the line the
// operator asked for on a dimmed frame. The clip keeps its own length; this
// is an overlay on the end, not an extra card appended after it.
// ---------------------------------------------------------------------------
const CtaEndcardOverlay: React.FC<{ text: string; accentColor: string }> = ({
  text,
  accentColor,
}) => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();

  const fontSize = Math.round(width * 0.082);
  const inset = Math.round(width * SAFE_MARGIN);

  const fadeIn = interpolate(frame, [0, 12], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const rise = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 90 },
  });

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <AbsoluteFill
        style={{ background: "rgba(0,0,0,0.68)", opacity: fadeIn }}
      />
      <AbsoluteFill
        style={{
          justifyContent: "center",
          alignItems: "center",
          paddingLeft: inset,
          paddingRight: inset,
          opacity: fadeIn,
        }}
      >
        <div
          style={{
            width: `${Math.round(rise * 24)}%`,
            height: Math.max(3, Math.round(fontSize * 0.07)),
            background: accentColor,
            borderRadius: 999,
            marginBottom: Math.round(fontSize * 0.5),
          }}
        />
        <div
          style={{
            fontFamily: FONT_STACK,
            fontWeight: 800,
            fontSize,
            lineHeight: 1.16,
            letterSpacing: "-0.01em",
            color: "#FFFFFF",
            textAlign: "center",
            textShadow: "0 6px 24px rgba(0,0,0,0.6)",
            transform: `translateY(${interpolate(
              rise,
              [0, 1],
              [Math.round(fontSize * 0.5), 0]
            )}px)`,
          }}
        >
          {text}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// The frame both templates share: the clip full bleed, with the overlay in
// its own Sequence so it carries a local frame counter and mounts exactly on
// the frame the caller asked for.
// ---------------------------------------------------------------------------
const MotionFrame: React.FC<{
  videoSrc: string;
  inSeconds: number;
  outSeconds: number;
  children: React.ReactNode;
}> = ({ videoSrc, inSeconds, outSeconds, children }) => {
  const { fps, durationInFrames } = useVideoConfig();

  const from = Math.max(0, Math.round(inSeconds * fps));
  const end =
    outSeconds > inSeconds
      ? Math.round(outSeconds * fps)
      : durationInFrames;
  const overlayFrames = Math.max(1, end - from);

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <OffthreadVideo
        src={resolveAsset(videoSrc)}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />
      <Sequence from={from} durationInFrames={overlayFrames}>
        {children}
      </Sequence>
    </AbsoluteFill>
  );
};

export const HookTitle: React.FC<MotionTemplateProps> = ({
  videoSrc,
  text,
  inSeconds,
  outSeconds,
  accentColor = DEFAULT_ACCENT,
}) => (
  <MotionFrame
    videoSrc={videoSrc}
    inSeconds={inSeconds}
    outSeconds={outSeconds}
  >
    <HookTitleOverlay text={text} accentColor={accentColor} />
  </MotionFrame>
);

export const CtaEndcard: React.FC<MotionTemplateProps> = ({
  videoSrc,
  text,
  inSeconds,
  outSeconds,
  accentColor = DEFAULT_ACCENT,
}) => (
  <MotionFrame
    videoSrc={videoSrc}
    inSeconds={inSeconds}
    outSeconds={outSeconds}
  >
    <CtaEndcardOverlay text={text} accentColor={accentColor} />
  </MotionFrame>
);
