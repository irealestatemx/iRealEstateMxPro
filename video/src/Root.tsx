import React from "react";
import { Composition } from "remotion";
import { PropertyReel, PropertyReelSchema } from "./PropertyReel";

export const Root: React.FC = () => {
  return (
    <Composition
      id="PropertyReel"
      component={PropertyReel}
      durationInFrames={750} // 25 seconds at 30fps
      fps={30}
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
    />
  );
};
