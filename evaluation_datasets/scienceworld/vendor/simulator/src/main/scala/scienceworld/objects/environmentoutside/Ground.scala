package scienceworld.objects.environmentoutside

import scienceworld.objects.containers.Container
import scienceworld.properties.{IsOpenUnclosableContainer, SoilProp}
import scienceworld.struct.EnvObject
import scienceworld.struct.EnvObject.MODE_CURSORY_DETAIL
import util.StringHelpers

class Ground extends EnvObject {
  this.name = "ground"

  this.propMaterial = Some(new SoilProp)
  this.propContainer = Some(new IsOpenUnclosableContainer)

  override def tick():Boolean = {
    // Anything placed on ground is automatically moved to parent container (just to keep the semantics simpler)
    val container = this.getContainer()
    if (container.isDefined) {
      for (cObj <- this.getContainedObjects()) {
        container.get.addObject(cObj)
      }
    }

    super.tick()
  }

  override def getReferents(): Set[String] = {
    Set("ground", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    return "the " + this.getDescriptName()
    /*
    val containedObjects = this.getContainedObjects()
    if (containedObjects.size == 0) {
      return "the " + this.name
    } else {
      return "the " + this.name + " (containing " + StringHelpers.objectListToStringDescription(containedObjects, this, mode=MODE_CURSORY_DETAIL, multiline = false) + ")"
    }
    */
  }

}

class Hole extends Container {
  this.name = "hole"

  //this.propMaterial = Some(new SoilProp)
  this.propContainer = Some(new IsOpenUnclosableContainer)

  override def getReferents(): Set[String] = {
    Set("hole", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    val containedObjects = this.getContainedObjects()
    if (containedObjects.size == 0) {
      return "a hole " + this.getDescriptName()
    } else {
      return "a " + this.getDescriptName() + " (containing " + StringHelpers.objectListToStringDescription(containedObjects, this, mode=MODE_CURSORY_DETAIL, multiline = false) + ")"
    }

  }

}
