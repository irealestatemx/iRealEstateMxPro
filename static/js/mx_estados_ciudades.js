/* ============================================================
   México — Estados y sus municipios/ciudades
   Fuente: catálogo INEGI. Usado para poblar el selector de
   ciudad en función del estado en el formulario de propiedades.
   window.MX_ESTADOS_CIUDADES = { "Estado": ["Ciudad", ...], ... }
   El campo de ciudad permite además texto libre (datalist),
   por si algún municipio no está en la lista.
   ============================================================ */
window.MX_ESTADOS_CIUDADES = {
  "Aguascalientes": ["Aguascalientes","Asientos","Calvillo","Cosío","El Llano","Jesús María","Pabellón de Arteaga","Rincón de Romos","San Francisco de los Romo","San José de Gracia","Tepezalá"],
  "Baja California": ["Ensenada","Mexicali","Playas de Rosarito","San Felipe","San Quintín","Tecate","Tijuana"],
  "Baja California Sur": ["Comondú","La Paz","Loreto","Los Cabos","Mulegé"],
  "Campeche": ["Calakmul","Calkiní","Campeche","Candelaria","Carmen","Champotón","Dzitbalché","Escárcega","Hecelchakán","Hopelchén","Palizada","Seybaplaya","Tenabo"],
  "Chiapas": ["Comitán de Domínguez","Chiapa de Corzo","Ocosingo","Palenque","San Cristóbal de las Casas","Tapachula","Tonalá","Tuxtla Gutiérrez","Villaflores"],
  "Chihuahua": ["Camargo","Chihuahua","Cuauhtémoc","Delicias","Hidalgo del Parral","Jiménez","Juárez","Meoqui","Nuevo Casas Grandes","Ojinaga"],
  "Ciudad de México": ["Álvaro Obregón","Azcapotzalco","Benito Juárez","Coyoacán","Cuajimalpa de Morelos","Cuauhtémoc","Gustavo A. Madero","Iztacalco","Iztapalapa","La Magdalena Contreras","Miguel Hidalgo","Milpa Alta","Tláhuac","Tlalpan","Venustiano Carranza","Xochimilco"],
  "Coahuila": ["Acuña","Allende","Arteaga","Castaños","Frontera","Matamoros","Monclova","Múzquiz","Nava","Parras","Piedras Negras","Ramos Arizpe","Sabinas","Saltillo","San Buenaventura","San Pedro","Torreón"],
  "Colima": ["Armería","Colima","Comala","Coquimatlán","Cuauhtémoc","Ixtlahuacán","Manzanillo","Minatitlán","Tecomán","Villa de Álvarez"],
  "Durango": ["Canatlán","Durango","Gómez Palacio","Guadalupe Victoria","Lerdo","Nuevo Ideal","Pueblo Nuevo","Santiago Papasquiaro","Vicente Guerrero"],
  "Estado de México": ["Atizapán de Zaragoza","Chalco","Chimalhuacán","Coacalco de Berriozábal","Cuautitlán","Cuautitlán Izcalli","Ecatepec de Morelos","Huixquilucan","Ixtapaluca","Metepec","Naucalpan de Juárez","Nezahualcóyotl","Nicolás Romero","Tecámac","Texcoco","Tlalnepantla de Baz","Toluca","Tultitlán","Valle de Bravo","Zinacantepec"],
  "Guanajuato": ["Abasolo","Acámbaro","Apaseo el Alto","Apaseo el Grande","Atarjea","Celaya","Comonfort","Coroneo","Cortazar","Cuerámaro","Doctor Mora","Dolores Hidalgo","Guanajuato","Huanímaro","Irapuato","Jaral del Progreso","Jerécuaro","León","Manuel Doblado","Moroleón","Ocampo","Pénjamo","Pueblo Nuevo","Purísima del Rincón","Romita","Salamanca","Salvatierra","San Diego de la Unión","San Felipe","San Francisco del Rincón","San José Iturbide","San Luis de la Paz","San Miguel de Allende","Santa Catarina","Santa Cruz de Juventino Rosas","Santiago Maravatío","Silao de la Victoria","Tarandacuao","Tarimoro","Tierra Blanca","Uriangato","Valle de Santiago","Victoria","Villagrán","Xichú","Yuriria"],
  "Guerrero": ["Acapulco de Juárez","Chilpancingo de los Bravo","Coyuca de Benítez","Iguala de la Independencia","Ometepec","Taxco de Alarcón","Tlapa de Comonfort","Zihuatanejo de Azueta"],
  "Hidalgo": ["Actopan","Apan","Huejutla de Reyes","Ixmiquilpan","Mineral de la Reforma","Pachuca de Soto","Tepeji del Río de Ocampo","Tizayuca","Tula de Allende","Tulancingo de Bravo"],
  "Jalisco": ["Ameca","Arandas","Autlán de Navarro","Chapala","Ciudad Guzmán","El Salto","Guadalajara","Lagos de Moreno","Ocotlán","Puerto Vallarta","Tepatitlán de Morelos","Tlajomulco de Zúñiga","Tlaquepaque","Tonalá","Tototlán","Zapopan","Zapotlanejo"],
  "Michoacán": ["Apatzingán","Ciudad Hidalgo","Lázaro Cárdenas","La Piedad","Morelia","Pátzcuaro","Sahuayo","Uruapan","Zamora","Zitácuaro"],
  "Morelos": ["Cuautla","Cuernavaca","Emiliano Zapata","Jiutepec","Jojutla","Temixco","Tepoztlán","Xochitepec","Yautepec","Zacatepec"],
  "Nayarit": ["Acaponeta","Bahía de Banderas","Compostela","Ixtlán del Río","San Blas","Santiago Ixcuintla","Tepic","Tuxpan","Xalisco"],
  "Nuevo León": ["Apodaca","Cadereyta Jiménez","García","General Escobedo","Guadalupe","Juárez","Linares","Montemorelos","Monterrey","San Nicolás de los Garza","San Pedro Garza García","Santa Catarina","Santiago"],
  "Oaxaca": ["Huajuapan de León","Juchitán de Zaragoza","Oaxaca de Juárez","Salina Cruz","San Juan Bautista Tuxtepec","Santa Cruz Xoxocotlán","Santa Lucía del Camino"],
  "Puebla": ["Amozoc","Atlixco","Cholula","Cuautlancingo","Huauchinango","Izúcar de Matamoros","Puebla","San Andrés Cholula","San Martín Texmelucan","San Pedro Cholula","Tehuacán","Teziutlán"],
  "Querétaro": ["Amealco de Bonfil","Cadereyta de Montes","Colón","Corregidora","El Marqués","Ezequiel Montes","Huimilpan","Jalpan de Serra","Pedro Escobedo","Querétaro","San Juan del Río","Tequisquiapan"],
  "Quintana Roo": ["Bacalar","Benito Juárez (Cancún)","Chetumal","Cozumel","Felipe Carrillo Puerto","Isla Mujeres","Playa del Carmen (Solidaridad)","Tulum"],
  "San Luis Potosí": ["Ciudad Valles","Matehuala","Rioverde","Salinas","San Luis Potosí","Soledad de Graciano Sánchez","Tamazunchale","Villa de Reyes"],
  "Sinaloa": ["Ahome (Los Mochis)","Culiacán","El Fuerte","Guasave","Guamúchil (Salvador Alvarado)","Mazatlán","Navolato"],
  "Sonora": ["Agua Prieta","Caborca","Cajeme (Ciudad Obregón)","Guaymas","Hermosillo","Navojoa","Nogales","Puerto Peñasco","San Luis Río Colorado"],
  "Tabasco": ["Cárdenas","Centro (Villahermosa)","Comalcalco","Cunduacán","Huimanguillo","Macuspana","Paraíso","Tenosique"],
  "Tamaulipas": ["Altamira","Ciudad Madero","Ciudad Victoria","Matamoros","Nuevo Laredo","Reynosa","Río Bravo","Tampico","El Mante"],
  "Tlaxcala": ["Apizaco","Calpulalpan","Chiautempan","Huamantla","Tlaxcala","Zacatelco"],
  "Veracruz": ["Boca del Río","Coatzacoalcos","Córdoba","Minatitlán","Orizaba","Poza Rica de Hidalgo","Tuxpan","Veracruz","Xalapa"],
  "Yucatán": ["Kanasín","Mérida","Motul","Progreso","Tekax","Ticul","Umán","Valladolid"],
  "Zacatecas": ["Calera","Fresnillo","Guadalupe","Jerez","Juchipila","Loreto","Río Grande","Sombrerete","Valparaíso","Zacatecas"]
};
