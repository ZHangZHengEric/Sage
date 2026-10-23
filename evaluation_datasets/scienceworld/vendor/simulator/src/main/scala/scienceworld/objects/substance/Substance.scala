package scienceworld.objects.substance

import scienceworld.properties._
import scienceworld.struct.EnvObject

class Substance extends EnvObject {
  this.name = "substance"

  override def getReferents(): Set[String] = {
    Set("substance", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    return "a substance called " + this.getDescriptName()
  }
}


class Air extends Substance {
  this.name = "air"

  this.propMaterial = Some(new AirProp())

}


class Water extends Substance {
  this.name = "water"

  this.propMaterial = Some(new WaterProp())

}

class Ice extends Substance {
  this.propMaterial = Some(new WaterProp())
  this.propMaterial.get.temperatureC = -10.0f

  this.name = this.propMaterial.get.nameInStateOfMatter("liquid")
}


// Metals
class Lead extends Substance {
  this.name = "lead"
  this.propMaterial = Some(new LeadProp())
}

class Tin extends Substance {
  this.name = "tin"
  this.propMaterial = Some(new TinProp())
}

class Mercury extends Substance {
  this.name = "mercury"
  this.propMaterial = Some(new MercuryProp())
}

class Gallium extends Substance {
  this.name = "gallium"
  this.propMaterial = Some(new GalliumProp())
}

class Caesium extends Substance {
  this.name = "caesium"
  this.propMaterial = Some(new CaesiumProp)
}

// Other
class Soap extends Substance {
  this.name = "soap"
  this.propMaterial = Some(new SoapProp)
}

class Rubber extends Substance {
  this.name = "rubber"
  this.propMaterial = Some (new RubberProp)
}

class Wood extends Substance {
  this.name = "wood"
  this.propMaterial = Some (new WoodProp)
}

class WoodBlock extends Substance {
  this.name = "wood block"
  this.propMaterial = Some (new WoodProp)

  override def getReferents():Set[String] = {
    Set("block", this.name, this.getDescriptName())
  }

  override def getDescription(mode: Int): String = {
    return "a " + this.getDescriptName()
  }
}

class SteelBlock extends Substance {
  this.name = "steel block"
  this.propMaterial = Some (new SteelProp)

  override def getReferents():Set[String] = {
    Set("block", this.name, this.getDescriptName())
  }

  override def getDescription(mode: Int): String = {
    return "a " + this.getDescriptName()
  }
}

class Brick extends Substance {
  this.name = "brick"
  this.propMaterial = Some (new BrickProp)

  override def getDescription(mode: Int): String = {
    return "a " + this.getDescriptName()
  }
}

// Combustion products
class Ash extends Substance {
  this.name = "ash"
  this.propMaterial = Some (new AshProp)
}


// Substances
class Sodium extends Substance {
  this.name = "sodium"
  this.propMaterial = Some( new SodiumProp )
}

class SodiumChloride extends Substance {
  this.name = "sodium chloride"
  this.propMaterial = Some( new SodiumChlorideProp )
}

class SaltWater extends Substance {
  this.name = "salt water"
  this.propMaterial = Some( new SaltWaterProp )
}

class SoapyWater extends Substance {
  this.name = "soapy water"
  this.propMaterial = Some( new SoapyWaterProp )
}


//##
class SodiumBicarbonate extends Substance {
  this.name = "sodium bicarbonate"
  this.propMaterial = Some( new SodiumBicarbonateProp() )
}

class AceticAcid extends Substance {
  this.name = "acetic acid"
  this.propMaterial = Some( new AceticAcidProp() )
}

class SodiumAcetate extends Substance {
  this.name = "sodium acetate"
  this.propMaterial = Some( new SodiumAcetateProp() )
}


class IronBlock extends Substance {
  this.name = "iron block"
  this.propMaterial = Some (new IronProp)

  override def getReferents():Set[String] = {
    Set("block", this.name, this.getDescriptName())
  }

  override def getDescription(mode: Int): String = {
    return "a " + this.getDescriptName()
  }
}

class Rust extends Substance {
  this.name = "rust"
  this.propMaterial = Some (new RustProp)
}

class Sugar extends Substance {
  this.name = "sugar"
  this.propMaterial = Some (new SugarProp)
}

class SugarWater extends Substance {
  this.name = "sugar water"
  this.propMaterial = Some (new SugarProp)
}
