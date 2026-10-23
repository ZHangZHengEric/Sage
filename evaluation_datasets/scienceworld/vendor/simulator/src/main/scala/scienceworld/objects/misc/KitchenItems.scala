package scienceworld.objects.misc

import scienceworld.properties.{AirProp, AluminumProp, MetalProp, PlasticProp, SteelProp}
import scienceworld.struct.EnvObject


class ForkMetal extends EnvObject {
  this.name = "metal fork"

  this.propMaterial = Some(new SteelProp())

  override def getReferents(): Set[String] = {
    Set(this.name, this.propMaterial.get.substanceName + " fork", this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    return "A " + this.getDescriptName()

  }
}

class ForkPlastic extends EnvObject {
  this.name = "plastic fork"

  this.propMaterial = Some(new PlasticProp())

  override def getReferents(): Set[String] = {
    Set(this.name, this.propMaterial.get.substanceName + " fork", this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    return "A " + this.getDescriptName()

  }
}

class PaperClip extends EnvObject {
  this.name = "paper clip"

  this.propMaterial = Some(new SteelProp())

  override def getReferents(): Set[String] = {
    Set(this.name, this.propMaterial.get.substanceName + " paper clip", this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    return "A " + this.getDescriptName()

  }
}

class AluminumFoil extends EnvObject {
  this.name = "aluminum foil"

  this.propMaterial = Some(new AluminumProp())

  override def getReferents(): Set[String] = {
    Set(this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    return "A " + this.getDescriptName()

  }
}
