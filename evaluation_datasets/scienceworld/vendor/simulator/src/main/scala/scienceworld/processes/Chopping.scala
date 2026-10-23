package scienceworld.processes

import scienceworld.objects.devices.Device
import scienceworld.objects.environmentoutside.{Ground, Hole}
import scienceworld.objects.livingthing.plant.{Plant, Soil, Tree}
import scienceworld.objects.substance.Wood
import scienceworld.struct.EnvObject

object Chopping {

  def doChop(obj:EnvObject):(Boolean, String) = {

    obj match {
      case t:Tree => {
        val container = t.getContainer()
        if (container.isEmpty) return (false, "ERROR: The " + t.name + " does not appear to be in a location.")

        if (t.isSeed()) return (true, "You can't chop a seed.")

        // First, create some wood
        val wood = new Wood()
        container.get.addObject(wood)

        // Second, delete the tree
        val treeName = t.getDescriptName()
        t.delete(expelContents = true)

        return (true, "You chop down the " + treeName + ", creating wood.")
      }
      case x:EnvObject => {
        // If the axe is used on a generic object that has device properties defined, then it will break that device
        if (x.propDevice.isDefined) {
          x.propDevice.get.isBroken = true
          return (true, "You hit the " + x.name + " with the axe, causing it to break.")
        }
      }
    }


    return (false, "It's not clear how to use an axe with that.")
  }
}
