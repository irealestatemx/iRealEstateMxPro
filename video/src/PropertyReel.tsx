import React from "react";
import {
  AbsoluteFill,
  Img,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  staticFile,
} from "remotion";
import { z } from "zod";

// ── Schema de props ──
export const PropertyReelSchema = z.object({
  photos: z.array(z.string()),
  operacion: z.string(),
  precio: z.string(),
  ubicacion: z.string(),
  recamaras: z.string(),
  banos: z.string(),
  metrosConstruidos: z.string(),
  metrosTerreno: z.string(),
  estacionamientos: z.string(),
  tipoPropiedad: z.string(),
  agenteNombre: z.string(),
  agenteTelefono: z.string(),
  agenteEmail: z.string(),
  logoHeaderUrl: z.string(),
  logoFullUrl: z.string(),
});

type Props = z.infer<typeof PropertyReelSchema>;

// ── Colores ──
const NAVY = "#1a3c5e";
const GOLD = "#c9a227";
const WHITE = "#ffffff";
const DARK_OVERLAY = "rgba(0,0,0,0.55)";

// ── Utilidades de animacion ──
function useFadeIn(delay = 0, duration = 15) {
  const frame = useCurrentFrame();
  return interpolate(frame, [delay, delay + duration], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
}

function useSlideUp(delay = 0, duration = 15) {
  const frame = useCurrentFrame();
  const progress = interpolate(frame, [delay, delay + duration], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const y = interpolate(progress, [0, 1], [60, 0]);
  return { opacity: progress, transform: `translateY(${y}px)` };
}

// ── Componente Ken Burns ──
const KenBurnsPhoto: React.FC<{ src: string; direction?: "in" | "out" }> = ({
  src,
  direction = "in",
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const scale =
    direction === "in"
      ? interpolate(frame, [0, durationInFrames], [1, 1.15], {
          extrapolateRight: "clamp",
        })
      : interpolate(frame, [0, durationInFrames], [1.15, 1], {
          extrapolateRight: "clamp",
        });

  const x =
    direction === "in"
      ? interpolate(frame, [0, durationInFrames], [0, -20], {
          extrapolateRight: "clamp",
        })
      : interpolate(frame, [0, durationInFrames], [-20, 0], {
          extrapolateRight: "clamp",
        });

  return (
    <AbsoluteFill>
      <Img
        src={src}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `scale(${scale}) translateX(${x}px)`,
        }}
      />
    </AbsoluteFill>
  );
};

// ── Gradiente inferior ──
const BottomGradient: React.FC<{ intensity?: number }> = ({
  intensity = 0.7,
}) => (
  <AbsoluteFill
    style={{
      background: `linear-gradient(
        to bottom,
        transparent 20%,
        rgba(0,0,0,${intensity * 0.3}) 50%,
        rgba(0,0,0,${intensity}) 100%
      )`,
    }}
  />
);

// ── Linea dorada decorativa ──
const GoldLine: React.FC<{ width?: string; delay?: number }> = ({
  width = "120px",
  delay = 0,
}) => {
  const style = useFadeIn(delay, 10);
  return (
    <div
      style={{
        width,
        height: 3,
        background: GOLD,
        borderRadius: 2,
        opacity: style,
        marginTop: 12,
        marginBottom: 12,
      }}
    />
  );
};

// ══════════════════════════════
// ESCENA 1: Portada con precio
// ══════════════════════════════
const SceneCover: React.FC<Props> = (props) => {
  const badgeStyle = useSlideUp(8, 12);
  const precioStyle = useSlideUp(14, 15);
  const ubicacionStyle = useSlideUp(22, 15);
  const logoOpacity = useFadeIn(4, 12);

  const photo = props.photos[0] || "";
  const badgeText = `EN ${props.operacion.toUpperCase()}`;

  return (
    <AbsoluteFill>
      {photo && <KenBurnsPhoto src={photo} direction="in" />}
      <BottomGradient intensity={0.8} />

      {/* Top: gold line + logo */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 6,
          background: GOLD,
        }}
      />

      {props.logoHeaderUrl && (
        <Img
          src={props.logoHeaderUrl}
          style={{
            position: "absolute",
            top: 60,
            right: 50,
            height: 55,
            opacity: logoOpacity,
          }}
        />
      )}

      {/* Bottom content */}
      <div
        style={{
          position: "absolute",
          bottom: 140,
          left: 60,
          right: 60,
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Badge */}
        <div style={badgeStyle}>
          <span
            style={{
              background: GOLD,
              color: NAVY,
              fontSize: 30,
              fontWeight: 800,
              padding: "10px 28px",
              borderRadius: 8,
              letterSpacing: 2,
              fontFamily: "sans-serif",
            }}
          >
            {badgeText}
          </span>
        </div>

        <GoldLine width="80px" delay={18} />

        {/* Precio */}
        <div style={precioStyle}>
          <div
            style={{
              fontSize: 72,
              fontWeight: 800,
              color: WHITE,
              fontFamily: "sans-serif",
              textShadow: "0 4px 20px rgba(0,0,0,0.5)",
              lineHeight: 1.1,
            }}
          >
            {props.precio}
          </div>
        </div>

        {/* Ubicacion */}
        <div style={ubicacionStyle}>
          <div
            style={{
              fontSize: 30,
              color: "rgba(255,255,255,0.8)",
              fontFamily: "sans-serif",
              marginTop: 16,
              textShadow: "0 2px 8px rgba(0,0,0,0.5)",
            }}
          >
            {props.ubicacion}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ══════════════════════════════
// ESCENA 2: Foto con specs
// ══════════════════════════════
const SceneSpecs: React.FC<Props & { photoIndex: number }> = (props) => {
  const photo = props.photos[props.photoIndex] || props.photos[0] || "";

  const specs: { label: string; value: string }[] = [];
  if (props.recamaras)
    specs.push({ label: "Recamaras", value: props.recamaras });
  if (props.banos) specs.push({ label: "Banos", value: props.banos });
  if (props.metrosConstruidos)
    specs.push({ label: "m2 Const.", value: props.metrosConstruidos });
  if (props.estacionamientos)
    specs.push({ label: "Estacion.", value: props.estacionamientos });

  return (
    <AbsoluteFill>
      {photo && <KenBurnsPhoto src={photo} direction="out" />}
      <BottomGradient intensity={0.75} />

      {/* Tipo propiedad badge top */}
      <div
        style={{
          position: "absolute",
          top: 80,
          left: 60,
        }}
      >
        <AnimatedBadge
          text={props.tipoPropiedad.toUpperCase()}
          delay={6}
        />
      </div>

      {/* Specs grid at bottom */}
      <div
        style={{
          position: "absolute",
          bottom: 160,
          left: 60,
          right: 60,
        }}
      >
        <GoldLine width="960px" delay={5} />
        <div
          style={{
            display: "flex",
            justifyContent: "space-around",
            gap: 20,
            marginTop: 20,
          }}
        >
          {specs.map((spec, i) => (
            <SpecItem
              key={spec.label}
              value={spec.value}
              label={spec.label}
              delay={10 + i * 6}
            />
          ))}
        </div>
        <GoldLine width="960px" delay={35} />
      </div>
    </AbsoluteFill>
  );
};

const AnimatedBadge: React.FC<{ text: string; delay: number }> = ({
  text,
  delay,
}) => {
  const style = useSlideUp(delay, 12);
  return (
    <div style={style}>
      <span
        style={{
          background: "rgba(26,60,94,0.85)",
          color: GOLD,
          fontSize: 28,
          fontWeight: 700,
          padding: "10px 24px",
          borderRadius: 6,
          fontFamily: "sans-serif",
          letterSpacing: 3,
          border: `2px solid ${GOLD}`,
        }}
      >
        {text}
      </span>
    </div>
  );
};

const SpecItem: React.FC<{
  value: string;
  label: string;
  delay: number;
}> = ({ value, label, delay }) => {
  const style = useSlideUp(delay, 12);
  return (
    <div
      style={{
        ...style,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        flex: 1,
      }}
    >
      <div
        style={{
          fontSize: 56,
          fontWeight: 800,
          color: WHITE,
          fontFamily: "sans-serif",
          textShadow: "0 3px 12px rgba(0,0,0,0.5)",
        }}
      >
        {value}
      </div>
      <div
        style={{
          fontSize: 22,
          color: GOLD,
          fontFamily: "sans-serif",
          fontWeight: 600,
          marginTop: 4,
          letterSpacing: 1,
          textTransform: "uppercase",
        }}
      >
        {label}
      </div>
    </div>
  );
};

// ══════════════════════════════
// ESCENA 3: Foto adicional con detalle
// ══════════════════════════════
const SceneDetail: React.FC<Props & { photoIndex: number }> = (props) => {
  const photo = props.photos[props.photoIndex] || props.photos[0] || "";
  const precioStyle = useSlideUp(8, 12);
  const ubicStyle = useSlideUp(16, 12);

  return (
    <AbsoluteFill>
      {photo && <KenBurnsPhoto src={photo} direction="in" />}
      <BottomGradient intensity={0.65} />

      <div
        style={{
          position: "absolute",
          bottom: 180,
          left: 60,
          right: 60,
        }}
      >
        <div style={precioStyle}>
          <div
            style={{
              fontSize: 54,
              fontWeight: 800,
              color: WHITE,
              fontFamily: "sans-serif",
              textShadow: "0 3px 15px rgba(0,0,0,0.5)",
            }}
          >
            {props.precio}
          </div>
        </div>
        <GoldLine width="200px" delay={14} />
        <div style={ubicStyle}>
          <div
            style={{
              fontSize: 28,
              color: "rgba(255,255,255,0.75)",
              fontFamily: "sans-serif",
            }}
          >
            {props.ubicacion}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ══════════════════════════════
// ESCENA FINAL: Contacto
// ══════════════════════════════
const SceneContact: React.FC<Props> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const logoScale = spring({ frame, fps, from: 0.8, to: 1, durationInFrames: 20 });
  const logoOpacity = useFadeIn(0, 15);
  const nameStyle = useSlideUp(12, 12);
  const phoneStyle = useSlideUp(18, 12);
  const emailStyle = useSlideUp(24, 12);
  const ctaStyle = useSlideUp(35, 15);

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(160deg, ${NAVY} 0%, #0d1f33 100%)`,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {/* Decorative gold lines */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 6,
          background: GOLD,
        }}
      />
      <div
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          right: 0,
          height: 6,
          background: GOLD,
        }}
      />

      {/* Logo */}
      {props.logoFullUrl && (
        <Img
          src={props.logoFullUrl}
          style={{
            height: 200,
            marginBottom: 60,
            opacity: logoOpacity,
            transform: `scale(${logoScale})`,
          }}
        />
      )}

      {/* Gold divider */}
      <GoldLine width="300px" delay={8} />

      {/* Agent info */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 16,
          marginTop: 20,
        }}
      >
        <div style={nameStyle}>
          <div
            style={{
              fontSize: 44,
              fontWeight: 700,
              color: WHITE,
              fontFamily: "sans-serif",
            }}
          >
            {props.agenteNombre}
          </div>
        </div>

        <div style={phoneStyle}>
          <div
            style={{
              fontSize: 34,
              color: GOLD,
              fontFamily: "sans-serif",
              fontWeight: 600,
            }}
          >
            Tel: {props.agenteTelefono}
          </div>
        </div>

        <div style={emailStyle}>
          <div
            style={{
              fontSize: 28,
              color: "rgba(255,255,255,0.6)",
              fontFamily: "sans-serif",
            }}
          >
            {props.agenteEmail}
          </div>
        </div>
      </div>

      {/* CTA */}
      <div style={ctaStyle}>
        <div
          style={{
            marginTop: 60,
            background: GOLD,
            color: NAVY,
            fontSize: 32,
            fontWeight: 800,
            padding: "18px 50px",
            borderRadius: 12,
            fontFamily: "sans-serif",
            letterSpacing: 1,
          }}
        >
          AGENDA TU VISITA HOY
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ══════════════════════════════
// COMPOSICION PRINCIPAL
// ══════════════════════════════
export const PropertyReel: React.FC<Props> = (props) => {
  const SCENE_FRAMES = 120; // 4 seconds per scene at 30fps
  const COVER_FRAMES = 150; // 5 seconds for cover
  const CONTACT_FRAMES = 180; // 6 seconds for contact

  // Build scenes based on available photos
  const numPhotos = props.photos.length;
  let currentFrame = 0;

  const scenes: React.ReactNode[] = [];

  // Scene 1: Cover (always)
  scenes.push(
    <Sequence key="cover" from={currentFrame} durationInFrames={COVER_FRAMES}>
      <SceneCover {...props} />
    </Sequence>
  );
  currentFrame += COVER_FRAMES;

  // Scene 2: Specs (use photo index 1 or 0)
  if (numPhotos > 0) {
    const specPhotoIdx = numPhotos > 1 ? 1 : 0;
    scenes.push(
      <Sequence key="specs" from={currentFrame} durationInFrames={SCENE_FRAMES}>
        <SceneSpecs {...props} photoIndex={specPhotoIdx} />
      </Sequence>
    );
    currentFrame += SCENE_FRAMES;
  }

  // Scenes 3+: Detail photos
  const detailStartIdx = numPhotos > 2 ? 2 : 0;
  const maxDetailScenes = Math.min(numPhotos - detailStartIdx, 3); // max 3 detail scenes
  for (let i = 0; i < maxDetailScenes; i++) {
    const photoIdx = detailStartIdx + i;
    if (photoIdx < numPhotos) {
      scenes.push(
        <Sequence
          key={`detail-${i}`}
          from={currentFrame}
          durationInFrames={SCENE_FRAMES}
        >
          <SceneDetail {...props} photoIndex={photoIdx} />
        </Sequence>
      );
      currentFrame += SCENE_FRAMES;
    }
  }

  // Final: Contact
  scenes.push(
    <Sequence
      key="contact"
      from={currentFrame}
      durationInFrames={CONTACT_FRAMES}
    >
      <SceneContact {...props} />
    </Sequence>
  );

  return (
    <AbsoluteFill style={{ background: "#000" }}>
      {scenes}
    </AbsoluteFill>
  );
};
