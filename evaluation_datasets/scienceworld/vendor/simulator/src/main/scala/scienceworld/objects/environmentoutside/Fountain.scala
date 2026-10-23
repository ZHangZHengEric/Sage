package scienceworld.objects.environmentoutside

import scienceworld.objects.containers.Container
import scienceworld.objects.substance.Water
import scienceworld.properties.{CeramicProp, IsOpenUnclosableContainer}

/*
 * A water fountain with infinite water
 */
class Fountain extends Container {
  this.name = "fountain"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new CeramicProp())

  override def tick(): Boolean = {
    // Add water in the fountain if there is none
    if (this.getContainedObjectsOfType[Water]().size == 0) {
      this.addObject( new Water() )
    }

    super.tick()
  }


  override def getReferents(): Set[String] = {
    Set("fountain", this.name, this.getDescriptName())
  }


}
