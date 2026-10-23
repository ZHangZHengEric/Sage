package scienceworld.objects.containers

import scienceworld.properties.{IsOpenUnclosableContainer, SteelProp, WoodProp}


/*
 * Sewer
 */

// A container that collects things from drains, and is not generally seen by the user (but required for the draining physics to work)
class Sewer extends Container {
  this.name = "sewer"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new SteelProp())

  override def getReferents(): Set[String] = {
    Set(this.name, this.getDescriptName())
  }

}
