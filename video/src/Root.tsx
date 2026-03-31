import React from "react";
import { Composition } from "remotion";
import { PropertyReel, PropertyReelSchema } from "./PropertyReel";
import { z } from "zod";

const FPS = 30;
const COVER_FRAMES = 150;    // 5s
const SCENE_FRAMES = 120;    // 4s
const CONTACT_FRAMES = 180;  // 6s

type Props = z.infer<typeof PropertyReelSchema>;

function calculateDuration(props: Props): number {
  const numPhotos = props.photos.length;
  const specFrames = numPhotos > 0 ? SCENE_FRAMES : 0;
  const detailScenes = Math.min(Math.max(numPhotos - 2, 0), 3);
  const detailFrames = detailScenes * SCENE_FRAMES;
  return COVER_FRAMES + specFrames + detailFrames + CONTACT_FRAMES;
}

export const Root: React.FC = () => {
  return (
    <Composition
      id="PropertyReel"
      component={PropertyReel}
      fps={FPS}
      width={1080}
      height={1920}
      schema={PropertyReelSchema}
      defaultProps={{
        photos: [],
        operacion: "Venta",
        precio: "$3,500,000 MXN",
        ubicacion: "Col. Jardines del Moral, Leon, Guanajuato",
        recamaras: "3",
        banos: "2.5",
        metrosConstruidos: "180",
        metrosTerreno: "250",
        estacionamientos: "2",
        tipoPropiedad: "Casa",
        agenteNombre: "Maria Gonzalez",
        agenteTelefono: "477 123 4567",
        agenteEmail: "maria@agencia.com",
        logoHeaderUrl: "",
        logoFullUrl: "",
      }}
      calculateMetadata={({ props }) => {
        return {
          durationInFrames: calculateDuration(props),
        };
      }}
      durationInFrames={900}
    />
  );
};
