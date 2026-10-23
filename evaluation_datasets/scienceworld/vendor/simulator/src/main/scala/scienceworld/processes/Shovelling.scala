package scienceworld.processes

import scienceworld.objects.containers.FlowerPot
import scienceworld.objects.environmentoutside.{Ground, Hole}
import scienceworld.objects.livingthing.plant.Soil
import scienceworld.struct.EnvObject

class Shovelling {

}

object Shovelling {


  def doShovel(obj:Object):(Boolean, String) = {

    obj match {
      case g:Ground => {
        val container = g.getContainer()
        if (container.isEmpty) return (false, "ERROR: The ground does not appear to be in a location.")

        // First, create a hole in the ground
        val hole = new Hole()
        container.get.addObject(hole)

        // Second, create soil and add it to the ground
        val soil = new Soil()
        container.get.addObject(soil)

        return (true, "You dig a hole in the ground, and place the soil nearby.")
      }
      case _ => { }
    }


    return (false, "It's not clear how to shovel that.")
  }

}
