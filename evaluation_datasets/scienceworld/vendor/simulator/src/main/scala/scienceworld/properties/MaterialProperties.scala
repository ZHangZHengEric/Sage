package scienceworld.properties

trait MaterialProperties {
  var substanceName:String            = "none"
  var nameInStateOfMatter:Map[String, String] = Map("solid" -> "none", "liquid" -> "none", "gas" -> "none")
  var color:String                    = "clear"
  // Thermal (all temperatures in C)
  var temperatureC:Double             = 0.0f
  var thermalConductivity:Double      = 1.0f
  var stateOfMatter:String            = "solid"
  var boilingPoint:Double             = 100.0f
  var meltingPoint:Double             = 0.0f
  var combustionPoint:Double          = 200.0f
  // Combustion
  var isCombusting:Boolean            = false
  var hasCombusted:Boolean            = false
  var combustionTicks:Int             = 100

  // Electrical
  var electricallyConductive:Boolean  = false

  // Friction
  var frictionCoefficient:Double      = 0.50      // 0 is no friction, 1 is complete friction


  def toJSON():String = {
    val os = new StringBuilder()
    os.append("{")
    os.append("\"substanceName\":\"" + this.substanceName + "\",")
    // os.append("\"nameInStateOfMatter\":\"" + this.nameInStateOfMatter + "\",")
    os.append("\"color\":\"" + this.color + "\",")
    os.append("\"temperatureC\":" + this.temperatureC + ",")
    os.append("\"thermalConductivity\":" + this.thermalConductivity + ",")
    os.append("\"stateOfMatter\":\"" + this.stateOfMatter + "\",")
    os.append("\"boilingPoint\":" + this.boilingPoint + ",")
    os.append("\"meltingPoint\":" + this.meltingPoint + ",")
    os.append("\"isCombusting\":" + this.isCombusting + ",")
    os.append("\"hasCombusted\":" + this.hasCombusted + ",")
    os.append("\"combustionTicks\":" + this.combustionTicks + ",")
    os.append("\"electricallyConductive\":" + this.electricallyConductive + ",")
    os.append("\"frictionCoefficient\":" + this.frictionCoefficient)
    os.append("}")

    return os.toString()
  }
}


class AirProp extends MaterialProperties {
  substanceName                   = "air"
  nameInStateOfMatter             = Map("solid" -> "solid air", "liquid" -> "liquid air", "gas" -> "air")
  color                           = "clear"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.01
  stateOfMatter                   = "gas"
  boilingPoint                    = -194.0f
  meltingPoint                    = -215.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = false

  // Friction
  frictionCoefficient             = 0.0      // 0 is no friction, 1 is complete friction

}

/*
 * Elements
 */
class SodiumProp extends MaterialProperties {
  substanceName                   = "sodium"
  nameInStateOfMatter             = Map("solid" -> "sodium", "liquid" -> "liquid sodium", "gas" -> "gaseous sodium")
  color                           = "grey"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.20
  stateOfMatter                   = "solid"
  boilingPoint                    = 881.0f
  meltingPoint                    = 98.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.0      // 0 is no friction, 1 is complete friction
}


/*
 * Metals
 */
class MetalProp extends MaterialProperties {
  substanceName                   = "metal"
  nameInStateOfMatter             = Map("solid" -> "metal", "liquid" -> "liquid metal", "gas" -> "gaseous metal")
  color                           = "grey"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "solid"
  boilingPoint                    = 2000.0f
  meltingPoint                    = 1000.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.5

}

class AluminumProp extends MetalProp {
  substanceName                   = "aluminum"
  nameInStateOfMatter             = Map("solid" -> "aluminum", "liquid" -> "liquid aluminum", "gas" -> "gaseous aluminum")
  color                           = "grey"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "solid"
  boilingPoint                    = 2470.0f
  meltingPoint                    = 660.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.45

}

class BrassProp extends MetalProp {
  substanceName                   = "brass"
  nameInStateOfMatter             = Map("solid" -> "brass", "liquid" -> "liquid brass", "gas" -> "gaseous brass")
  color                           = "brown"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "solid"
  boilingPoint                    = 1100.0f
  meltingPoint                    = 900.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.50

}

class BronzeProp extends MetalProp {
  substanceName                   = "bronze"
  nameInStateOfMatter             = Map("solid" -> "bronze", "liquid" -> "liquid bronze", "gas" -> "gaseous bronze")
  color                           = "brown"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "solid"
  boilingPoint                    = 2300.0f
  meltingPoint                    = 910.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.40

}

class CaesiumProp extends MetalProp {
  substanceName                   = "caesium"
  nameInStateOfMatter             = Map("solid" -> "solid caesium", "liquid" -> "liquid caesium", "gas" -> "gaseous caesium")
  color                           = "gold"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "solid"
  boilingPoint                    = 671.0f
  meltingPoint                    = 29.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.50

}

class CopperProp extends MetalProp {
  substanceName                   = "copper"
  nameInStateOfMatter             = Map("solid" -> "copper", "liquid" -> "liquid copper", "gas" -> "gaseous copper")
  color                           = "brown"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "solid"
  boilingPoint                    = 2500.0f
  meltingPoint                    = 1083.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.60

}

class GalliumProp extends MetalProp {
  substanceName                   = "gallium"
  nameInStateOfMatter             = Map("solid" -> "gallium", "liquid" -> "liquid gallium", "gas" -> "gaseous gallium")
  color                           = "silver"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "liquid"
  boilingPoint                    = 2400.0f
  meltingPoint                    = 30.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.0      // 0 is no friction, 1 is complete friction

}

class GoldProp extends MetalProp {
  substanceName                   = "gold"
  nameInStateOfMatter             = Map("solid" -> "gold", "liquid" -> "liquid gold", "gas" -> "gaseous gold")
  color                           = "brown"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "solid"
  boilingPoint                    = 2700.0f
  meltingPoint                    = 1063.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.0      // 0 is no friction, 1 is complete friction

}

class IronProp extends MetalProp {
  substanceName                   = "iron"
  nameInStateOfMatter             = Map("solid" -> "iron", "liquid" -> "liquid iron", "gas" -> "gaseous iron")
  color                           = "grey"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "solid"
  boilingPoint                    = 2862.0f
  meltingPoint                    = 1538.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.7

}

class LeadProp extends MetalProp {
  substanceName                   = "lead"
  nameInStateOfMatter             = Map("solid" -> "lead", "liquid" -> "liquid lead", "gas" -> "gaseous lead")
  color                           = "grey"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "solid"
  boilingPoint                    = 1740.0f
  meltingPoint                    = 327.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.43

}

class MercuryProp extends MetalProp {
  substanceName                   = "mercury"
  nameInStateOfMatter             = Map("solid" -> "solid mercury", "liquid" -> "liquid mercury", "gas" -> "gaseous mercury")
  color                           = "silver"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "liquid"
  boilingPoint                    = 357.0f
  meltingPoint                    = -39.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.1

}

class PlatinumProp extends MetalProp {
  substanceName                   = "platinum"
  nameInStateOfMatter             = Map("solid" -> "platinum", "liquid" -> "liquid platinum", "gas" -> "gaseous platinum")
  color                           = "grey"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "solid"
  boilingPoint                    = 4400.0f
  meltingPoint                    = 1770.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.8

}

class SiliconProp extends MetalProp {
  substanceName                   = "silicon"
  nameInStateOfMatter             = Map("solid" -> "silicon", "liquid" -> "liquid silicon", "gas" -> "gaseous silicon")
  color                           = "grey"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "solid"
  boilingPoint                    = 2600.0f
  meltingPoint                    = 1420.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.0      // 0 is no friction, 1 is complete friction

}

class SteelProp extends MetalProp {
  substanceName                   = "steel"
  nameInStateOfMatter             = Map("solid" -> "steel", "liquid" -> "liquid steel", "gas" -> "gaseous steel")
  color                           = "grey"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "solid"
  boilingPoint                    = 2900.0f
  meltingPoint                    = 1400.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.6

}

class TinProp extends MetalProp {
  substanceName                   = "tin"
  nameInStateOfMatter             = Map("solid" -> "tin", "liquid" -> "liquid tin", "gas" -> "gaseous tin")
  color                           = "grey"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "solid"
  boilingPoint                    = 2602.0f
  meltingPoint                    = 232.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.3

}

class TitaniumProp extends MetalProp {
  substanceName                   = "titanium"
  nameInStateOfMatter             = Map("solid" -> "titanium", "liquid" -> "liquid titanium", "gas" -> "gaseous titanium")
  color                           = "grey"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "solid"
  boilingPoint                    = 3200.0f
  meltingPoint                    = 1670.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.0      // 0 is no friction, 1 is complete friction

}

class ZincProp extends MetalProp {
  substanceName                   = "zinc"
  nameInStateOfMatter             = Map("solid" -> "zinc", "liquid" -> "liquid zinc", "gas" -> "gaseous zinc")
  color                           = "brown"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "solid"
  boilingPoint                    = 906.0f
  meltingPoint                    = 419.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.62

}

/*
 * Glass
 */
class GlassProp extends MaterialProperties {
  substanceName                   = "glass"
  nameInStateOfMatter             = Map("solid" -> "glass", "liquid" -> "liquid glass", "gas" -> "gaseous glass")
  color                           = "clear"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "solid"
  boilingPoint                    = 2200.0f
  meltingPoint                    = 1400.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.20

}

// Rust
class RustProp extends MetalProp {
  substanceName                   = "rust"
  nameInStateOfMatter             = Map()
  color                           = "red"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.90
  stateOfMatter                   = "solid"
  boilingPoint                    = 100001.0f
  meltingPoint                    = 100000.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.7

}

/*
 * Plastic
 */
class PlasticProp extends MaterialProperties {
  substanceName                   = "plastic"
  nameInStateOfMatter             = Map("solid" -> "plastic", "liquid" -> "liquid plastic", "gas" -> "gaseous plastic")
  color                           = "white"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 1.00
  stateOfMatter                   = "solid"
  boilingPoint                    = 300.0f
  meltingPoint                    = 200.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.1

}

/*
 * Ceramic
 */
class CeramicProp extends MaterialProperties {
  substanceName                   = "ceramic"
  nameInStateOfMatter             = Map("solid" -> "ceramic", "liquid" -> "liquid ceramic", "gas" -> "gaseous ceramic")
  color                           = "white"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.02
  stateOfMatter                   = "solid"
  boilingPoint                    = 10001.0f
  meltingPoint                    = 2000.0f
  combustionPoint                 = 10000.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.65

}



/*
 * Wood/Paper
 */
class WoodProp extends MaterialProperties {
  substanceName                   = "wood"
  nameInStateOfMatter             = Map()
  color                           = "brown"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.50
  stateOfMatter                   = "solid"
  boilingPoint                    = 10001.0f
  meltingPoint                    = 10000.0f
  combustionPoint                 = 350.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.2

}


class PaperProp extends MaterialProperties {
  substanceName                   = "paper"
  nameInStateOfMatter             = Map()
  color                           = "white"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.50
  stateOfMatter                   = "solid"
  boilingPoint                    = 10001.0f
  meltingPoint                    = 10000.0f
  combustionPoint                 = 210.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.2

}

/*
 * Sand paper
 */
class SandpaperProp extends MaterialProperties {
  substanceName                   = "sandpaper"
  nameInStateOfMatter             = Map()
  color                           = "brown"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.50
  stateOfMatter                   = "solid"
  boilingPoint                    = 10001.0f
  meltingPoint                    = 10000.0f
  combustionPoint                 = 230.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.98

}


/*
 * Cloth
 */
class CottonClothProp extends MaterialProperties {
  substanceName                   = "cloth"
  nameInStateOfMatter             = Map()
  color                           = "white"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.10
  stateOfMatter                   = "solid"
  boilingPoint                    = 10001.0f
  meltingPoint                    = 10000.0f
  combustionPoint                 = 300.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.3

}

/*
 * Rubber
 */
class RubberProp extends MaterialProperties {
  substanceName                   = "rubber"
  nameInStateOfMatter             = Map("solid" -> "rubber", "liquid" -> "liquid rubber", "gas" -> "gaseous rubber")
  color                           = "black"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.50
  stateOfMatter                   = "solid"
  boilingPoint                    = 10001.0f
  meltingPoint                    = 180.0f
  combustionPoint                 = 260.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.95      // 0 is no friction, 1 is complete friction

}


/*
 * Liquids
 */
class WaterProp extends MaterialProperties {
  substanceName                   = "water"
  nameInStateOfMatter             = Map("solid" -> "ice", "liquid" -> "water", "gas" -> "steam")
  color                           = "clear"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.5f
  stateOfMatter                   = "liquid"
  boilingPoint                    = 100.0f
  meltingPoint                    = 0.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.1

}


class OrangeJuiceProp extends MaterialProperties {
  substanceName                   = "orange juice"
  nameInStateOfMatter             = Map("solid" -> "solid orange juice", "liquid" -> "orange juice", "gas" -> "gaseous orange juice")
  color                           = "orange"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.5f
  stateOfMatter                   = "liquid"
  boilingPoint                    = 100.0f
  meltingPoint                    = 0.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.1

}

class AppleJuiceProp extends MaterialProperties {
  substanceName                   = "apple juice"
  nameInStateOfMatter             = Map("solid" -> "solid apple juice", "liquid" -> "apple juice", "gas" -> "gaseous apple juice")
  color                           = "yellow"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.5f
  stateOfMatter                   = "liquid"
  boilingPoint                    = 160.0f
  meltingPoint                    = -2.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.1

}

/*
 * Plants/Soil
 */
class SoilProp extends MaterialProperties {
  substanceName                   = "soil"
  nameInStateOfMatter             = Map()
  color                           = "brown"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.50
  stateOfMatter                   = "solid"
  boilingPoint                    = 10001.0f
  meltingPoint                    = 10000.0f
  combustionPoint                 = 10000.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.3      // 0 is no friction, 1 is complete friction  (GUESS)


}

class PlantMatterProp extends MaterialProperties {
  substanceName                   = "plant matter"
  nameInStateOfMatter             = Map()
  color                           = "green"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.50
  stateOfMatter                   = "solid"
  boilingPoint                    = 10001.0f
  meltingPoint                    = 10000.0f
  combustionPoint                 = 200.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.3      // 0 is no friction, 1 is complete friction  (GUESS)

}

class FlowerMatterProp extends MaterialProperties {
  substanceName                   = "flower matter"
  nameInStateOfMatter             = Map()
  color                           = "purple"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.50
  stateOfMatter                   = "solid"
  boilingPoint                    = 10001.0f
  meltingPoint                    = 10000.0f
  combustionPoint                 = 200.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.3      // 0 is no friction, 1 is complete friction  (GUESS)

}

class PollenMatterProp extends MaterialProperties {
  substanceName                   = "pollen matter"
  nameInStateOfMatter             = Map()
  color                           = "yellow"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.50
  stateOfMatter                   = "solid"
  boilingPoint                    = 10001.0f
  meltingPoint                    = 10000.0f
  combustionPoint                 = 200.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.5      // 0 is no friction, 1 is complete friction  (GUESS)

}


/*
 * Food matter
 */
class ChocolateProp extends MaterialProperties {
  substanceName                   = "chocolate"
  nameInStateOfMatter             = Map("solid" -> "solid chocolate", "liquid" -> "liquid chocolate", "gas" -> "gaseous chocolate")
  color                           = "brown"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.5f
  stateOfMatter                   = "solid"
  boilingPoint                    = 100000.0f
  meltingPoint                    = 30.0f
  combustionPoint                 = 95.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.32

}

// Rust
class SugarProp extends MaterialProperties {
  substanceName                   = "sugar"
  nameInStateOfMatter             = Map()
  color                           = "white"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.5f
  stateOfMatter                   = "solid"
  boilingPoint                    = 100000.0f
  meltingPoint                    = 186.0f      // Sucrose
  combustionPoint                 = 350.0f      // Sucrose
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.70      // 0 is no friction, 1 is complete friction (GUESS)
}

class MarshmallowProp extends MaterialProperties {
  substanceName                   = "marshmallow"
  nameInStateOfMatter             = Map("solid" -> "marshmallow", "liquid" -> "liquid marshmallow", "gas" -> "gaseous marshmallow")
  color                           = "white"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.5f
  stateOfMatter                   = "solid"
  boilingPoint                    = 100000.0f
  meltingPoint                    = 36.0f
  combustionPoint                 = 350.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.70      // 0 is no friction, 1 is complete friction (GUESS)

}

class SoapProp extends MaterialProperties {
  substanceName                   = "soap"
  nameInStateOfMatter             = Map("solid" -> "soap", "liquid" -> "liquid soap", "gas" -> "gaseous soap")
  color                           = "white"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.5f
  stateOfMatter                   = "solid"
  boilingPoint                    = 100000.0f
  meltingPoint                    = 140.0f
  combustionPoint                 = 537.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.05      // 0 is no friction, 1 is complete friction (GUESS)

}

class IceCreamProp extends MaterialProperties {
  substanceName                   = "ice cream"
  nameInStateOfMatter             = Map("solid" -> "ice cream", "liquid" -> "liquid ice cream", "gas" -> "gaseous ice cream")
  color                           = "white"
  // Thermal
  temperatureC                    = -15.0f
  thermalConductivity             = 0.5f
  stateOfMatter                   = "solid"
  boilingPoint                    = 101.0f
  meltingPoint                    = -10.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.1      // 0 is no friction, 1 is complete friction (GUESS)

}

class FlourProp extends MaterialProperties {
  substanceName                   = "flour"
  nameInStateOfMatter             = Map()
  color                           = "white"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.50
  stateOfMatter                   = "solid"
  boilingPoint                    = 10001.0f
  meltingPoint                    = 10000.0f
  combustionPoint                 = 380.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.5      // 0 is no friction, 1 is complete friction  (GUESS)

}

class JamProp extends MaterialProperties {
  substanceName                   = "jam"
  nameInStateOfMatter             = Map()     // TODO: Add different states?
  color                           = "red"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.50
  stateOfMatter                   = "solid"
  boilingPoint                    = 10001.0f
  meltingPoint                    = 10000.0f
  combustionPoint                 = 400.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.5      // 0 is no friction, 1 is complete friction  (GUESS)

}

class DoughProp extends MaterialProperties {
  substanceName                   = "dough"
  nameInStateOfMatter             = Map()
  color                           = "white"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.50
  stateOfMatter                   = "solid"
  boilingPoint                    = 10001.0f
  meltingPoint                    = 10000.0f
  combustionPoint                 = 380.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.5      // 0 is no friction, 1 is complete friction  (GUESS)

}

class NutProp extends MaterialProperties {
  substanceName                   = "nut"
  nameInStateOfMatter             = Map()
  color                           = "brown"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.50
  stateOfMatter                   = "solid"
  boilingPoint                    = 10001.0f
  meltingPoint                    = 10000.0f
  combustionPoint                 = 400.0f      // Guess
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.5      // 0 is no friction, 1 is complete friction  (GUESS)

}

class AshProp extends MaterialProperties {
  substanceName                   = "ash"
  nameInStateOfMatter             = Map()
  color                           = "grey"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.50
  stateOfMatter                   = "solid"
  boilingPoint                    = 10001.0f
  meltingPoint                    = 10000.0f
  combustionPoint                 = 10002.0f
  // Combustion
  isCombusting                    = false           // Has already combusted
  hasCombusted                    = true
  combustionTicks                 = 0
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.9      // 0 is no friction, 1 is complete friction (GUESS)


}


/*
 * Other chemicals
 */
class SodiumChlorideProp extends MaterialProperties {
  substanceName                   = "sodium chloride"
  nameInStateOfMatter             = Map("solid" -> "sodium chloride", "liquid" -> "liquid sodium chloride", "gas" -> "gaseous sodium chloride")
  color                           = "white"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.20
  stateOfMatter                   = "solid"
  boilingPoint                    = 1465.0f
  meltingPoint                    = 801.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.73

}

class AceticAcidProp extends MaterialProperties {
  substanceName                   = "acetic acid"
  nameInStateOfMatter             = Map("solid" -> "solid acetic acid", "liquid" -> "acetic acid", "gas" -> "gaseous acetic acid")
  color                           = "clear"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.20
  stateOfMatter                   = "solid"
  boilingPoint                    = 119.0f
  meltingPoint                    = 17.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.1

}

class SodiumBicarbonateProp extends MaterialProperties {
  substanceName                   = "sodium bicarbonate"
  nameInStateOfMatter             = Map()
  color                           = "white"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.20
  stateOfMatter                   = "solid"
  boilingPoint                    = 10001.0f
  meltingPoint                    = 10000.0f
  combustionPoint                 = 100.0f      // Technically not correct, but this is its decomposition temperature
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.73

}

class SodiumAcetateProp extends MaterialProperties {
  substanceName                   = "sodium acetate"
  nameInStateOfMatter             = Map("solid" -> "sodium bicarbonate", "liquid" -> "sodium bicarbonate", "gas" -> "sodium bicarbonate")
  color                           = "clear"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.50
  stateOfMatter                   = "solid"
  boilingPoint                    = 881.0f
  meltingPoint                    = 324.0f
  combustionPoint                 = 100000.0f      // Technically not correct, but this is its decomposition temperature
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.50

}

class SaltWaterProp extends MaterialProperties {
  substanceName                   = "salt water"
  nameInStateOfMatter             = Map("solid" -> "solid salt water", "liquid" -> "salt water", "gas" -> "gaseous salt water")
  color                           = "white"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.20
  stateOfMatter                   = "solid"
  boilingPoint                    = 110.0f
  meltingPoint                    = -2.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = true
  // Friction
  frictionCoefficient             = 0.15

}

class SoapyWaterProp extends MaterialProperties {
  substanceName                   = "soapy water"
  nameInStateOfMatter             = Map("solid" -> "solid soapy water", "liquid" -> "soapy water", "gas" -> "gaseous soapy water")
  color                           = "white"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.20
  stateOfMatter                   = "solid"
  boilingPoint                    = 105.0f
  meltingPoint                    = -1.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.06

}

class SugarWaterProp extends MaterialProperties {
  substanceName                   = "sugar water"
  nameInStateOfMatter             = Map("solid" -> "solid sugar water", "liquid" -> "sugar water", "gas" -> "gaseous sugar water")
  color                           = "white"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.20
  stateOfMatter                   = "solid"
  boilingPoint                    = 112.0f
  meltingPoint                    = -3.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.06

}

class BrickProp extends MaterialProperties {
  substanceName                   = "brick"
  nameInStateOfMatter             = Map()
  color                           = "red"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.10
  stateOfMatter                   = "solid"
  boilingPoint                    = 100001.0f
  meltingPoint                    = 1500.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.90

}

/*
 * Paint
 */
class GenericPaintProp extends MaterialProperties {
  color                           = "white"
  substanceName                   = this.color + "paint"
  val solidName                   = "dried " + this.color + " paint"
  val liquidName                  = this.color + " paint"
  val gasName                     = "gaseous " + this.color + " paint"
  nameInStateOfMatter             = Map("solid" -> solidName, "liquid" -> liquidName, "gas" -> gasName)

  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.20
  stateOfMatter                   = "liquid"
  boilingPoint                    = 10000.0f
  meltingPoint                    = 0.0f
  combustionPoint                 = 293.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.3      // 0 is no friction, 1 is complete friction (GUESS)

}

class WhitePaintProp extends GenericPaintProp {
  color                           = "white"
  substanceName                   = this.color + "paint"
  // Inferred
  override val solidName          = "dried " + this.color + " paint"
  override val liquidName         = this.color + " paint"
  override val gasName            = "gaseous " + this.color + " paint"
  nameInStateOfMatter             = Map("solid" -> solidName, "liquid" -> liquidName, "gas" -> gasName)
}

class BlackPaintProp extends GenericPaintProp {
  color                           = "black"
  substanceName                   = this.color + "paint"
  // Inferred
  override val solidName          = "dried " + this.color + " paint"
  override val liquidName         = this.color + " paint"
  override val gasName            = "gaseous " + this.color + " paint"
  nameInStateOfMatter             = Map("solid" -> solidName, "liquid" -> liquidName, "gas" -> gasName)
}

class RedPaintProp extends GenericPaintProp {
  color                           = "red"
  substanceName                   = this.color + "paint"
  // Inferred
  override val solidName          = "dried " + this.color + " paint"
  override val liquidName         = this.color + " paint"
  override val gasName            = "gaseous " + this.color + " paint"
  nameInStateOfMatter             = Map("solid" -> solidName, "liquid" -> liquidName, "gas" -> gasName)
}

class BluePaintProp extends GenericPaintProp {
  color                           = "blue"
  substanceName                   = this.color + "paint"
  // Inferred
  override val solidName          = "dried " + this.color + " paint"
  override val liquidName         = this.color + " paint"
  override val gasName            = "gaseous " + this.color + " paint"
  nameInStateOfMatter             = Map("solid" -> solidName, "liquid" -> liquidName, "gas" -> gasName)
}

class YellowPaintProp extends GenericPaintProp {
  color                           = "yellow"
  substanceName                   = this.color + "paint"
  // Inferred
  override val solidName          = "dried " + this.color + " paint"
  override val liquidName         = this.color + " paint"
  override val gasName            = "gaseous " + this.color + " paint"
  nameInStateOfMatter             = Map("solid" -> solidName, "liquid" -> liquidName, "gas" -> gasName)
}

class VioletPaintProp extends GenericPaintProp {
  color                           = "violet"
  substanceName                   = this.color + "paint"
  // Inferred
  override val solidName          = "dried " + this.color + " paint"
  override val liquidName         = this.color + " paint"
  override val gasName            = "gaseous " + this.color + " paint"
  nameInStateOfMatter             = Map("solid" -> solidName, "liquid" -> liquidName, "gas" -> gasName)
}

class GreenPaintProp extends GenericPaintProp {
  color                           = "green"
  substanceName                   = this.color + "paint"
  // Inferred
  override val solidName          = "dried " + this.color + " paint"
  override val liquidName         = this.color + " paint"
  override val gasName            = "gaseous " + this.color + " paint"
  nameInStateOfMatter             = Map("solid" -> solidName, "liquid" -> liquidName, "gas" -> gasName)
}

class OrangePaintProp extends GenericPaintProp {
  color                           = "orange"
  substanceName                   = this.color + "paint"
  // Inferred
  override val solidName          = "dried " + this.color + " paint"
  override val liquidName         = this.color + " paint"
  override val gasName            = "gaseous " + this.color + " paint"
  nameInStateOfMatter             = Map("solid" -> solidName, "liquid" -> liquidName, "gas" -> gasName)
}

class BrownPaintProp extends GenericPaintProp {
  color                           = "brown"
  substanceName                   = this.color + "paint"
  // Inferred
  override val solidName          = "dried " + this.color + " paint"
  override val liquidName         = this.color + " paint"
  override val gasName            = "gaseous " + this.color + " paint"
  nameInStateOfMatter             = Map("solid" -> solidName, "liquid" -> liquidName, "gas" -> gasName)
}

class YellowOrangePaintProp extends GenericPaintProp {
  color                           = "yellow-orange"
  substanceName                   = this.color + "paint"
  // Inferred
  override val solidName          = "dried " + this.color + " paint"
  override val liquidName         = this.color + " paint"
  override val gasName            = "gaseous " + this.color + " paint"
  nameInStateOfMatter             = Map("solid" -> solidName, "liquid" -> liquidName, "gas" -> gasName)
}

class RedOrangePaintProp extends GenericPaintProp {
  color                           = "red-orange"
  substanceName                   = this.color + "paint"
  // Inferred
  override val solidName          = "dried " + this.color + " paint"
  override val liquidName         = this.color + " paint"
  override val gasName            = "gaseous " + this.color + " paint"
  nameInStateOfMatter             = Map("solid" -> solidName, "liquid" -> liquidName, "gas" -> gasName)
}

class VioletRedPaintProp extends GenericPaintProp {
  color                           = "violet-red"
  substanceName                   = this.color + "paint"
  // Inferred
  override val solidName          = "dried " + this.color + " paint"
  override val liquidName         = this.color + " paint"
  override val gasName            = "gaseous " + this.color + " paint"
  nameInStateOfMatter             = Map("solid" -> solidName, "liquid" -> liquidName, "gas" -> gasName)
}

class BlueVioletPaintProp extends GenericPaintProp {
  color                           = "blue-violet"
  substanceName                   = this.color + "paint"
  // Inferred
  override val solidName          = "dried " + this.color + " paint"
  override val liquidName         = this.color + " paint"
  override val gasName            = "gaseous " + this.color + " paint"
  nameInStateOfMatter             = Map("solid" -> solidName, "liquid" -> liquidName, "gas" -> gasName)
}

class GreenBluePaintProp extends GenericPaintProp {
  color                           = "green-blue"
  substanceName                   = this.color + "paint"
  // Inferred
  override val solidName          = "dried " + this.color + " paint"
  override val liquidName         = this.color + " paint"
  override val gasName            = "gaseous " + this.color + " paint"
  nameInStateOfMatter             = Map("solid" -> solidName, "liquid" -> liquidName, "gas" -> gasName)
}

class YellowGreenPaintProp extends GenericPaintProp {
  color                           = "yellow-green"
  substanceName                   = this.color + "paint"
  // Inferred
  override val solidName          = "dried " + this.color + " paint"
  override val liquidName         = this.color + " paint"
  override val gasName            = "gaseous " + this.color + " paint"
  nameInStateOfMatter             = Map("solid" -> solidName, "liquid" -> liquidName, "gas" -> gasName)
}

// Red
// Blue
// Yellow
// Violet
// Green
// Orange
// Yellow-Orange
// Red-Orange
// Violet-red
// blue-violet
// green-blue
// green-yellow
// Brown
// Black
// White

/*
 * Materials of unknown friction
 */
class UnknownFrictionMaterial extends MaterialProperties {
  substanceName                   = "unknown material"
  nameInStateOfMatter             = Map()
  color                           = "grey"
  // Thermal
  temperatureC                    = 10.0f
  thermalConductivity             = 0.10
  stateOfMatter                   = "solid"
  boilingPoint                    = 100002.0f
  meltingPoint                    = 100001.0f
  combustionPoint                 = 100000.0f
  // Electrical
  electricallyConductive          = false
  // Friction
  frictionCoefficient             = 0.0
}

class UnknownFrictionMaterialA extends UnknownFrictionMaterial {
  substanceName                   = "unknown material A"
  frictionCoefficient             = 0.1
}

class UnknownFrictionMaterialB extends UnknownFrictionMaterial {
  substanceName                   = "unknown material B"
  frictionCoefficient             = 0.7
}

class UnknownFrictionMaterialC extends UnknownFrictionMaterial {
  substanceName                   = "unknown material C"
  frictionCoefficient             = 0.4
}

class UnknownFrictionMaterialD extends UnknownFrictionMaterial {
  substanceName                   = "unknown material D"
  frictionCoefficient             = 0.6
}

class UnknownFrictionMaterialE extends UnknownFrictionMaterial {
  substanceName                   = "unknown material E"
  frictionCoefficient             = 0.2
}

class UnknownFrictionMaterialF extends UnknownFrictionMaterial {
  substanceName                   = "unknown material F"
  frictionCoefficient             = 0.8
}

class UnknownFrictionMaterialG extends UnknownFrictionMaterial {
  substanceName                   = "unknown material G"
  frictionCoefficient             = 0.3
}

class UnknownFrictionMaterialH extends UnknownFrictionMaterial {
  substanceName                   = "unknown material H"
  frictionCoefficient             = 0.9
}

class UnknownFrictionMaterialJ extends UnknownFrictionMaterial {
  substanceName                   = "unknown material J"
  frictionCoefficient             = 0.9
}

class DefaultFrictionMaterialProp extends UnknownFrictionMaterial {
  substanceName                   = "unknown material J"
  frictionCoefficient             = 0.5
}
