package scienceworld.objects.livingthing.plant

import scienceworld.properties.SoilProp
import scienceworld.struct.EnvObject

class Soil extends EnvObject {
  this.name = "soil"

  this.propMaterial = Some(new SoilProp)

  override def getReferents(): Set[String] = {
    Set("soil", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    return this.getDescriptName()
  }

}
