package scienceworld.objects.environmentoutside

import scienceworld.objects.containers.Container
import scienceworld.properties.{CeramicProp, IsOpenUnclosableContainer, SoilProp}

class FirePit extends Container {
  this.name = "fire pit"

  this.propMaterial = Some(new CeramicProp)
  this.propContainer = Some(new IsOpenUnclosableContainer)

  override def getReferents(): Set[String] = {
    Set("fire pit", this.name, this.getDescriptName())
  }

}
