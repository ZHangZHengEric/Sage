package scienceworld.environments

import scienceworld.objects.containers.{BookShelf, GlassCup, MetalPot, Sewer, WoodCup}
import scienceworld.objects.agent.Agent
import scienceworld.objects.devices.{Freezer, Fridge, Sink, Stove, Thermometer, Toilet}
import scienceworld.objects.document.{BookFrankenstein, BookMobyDick}
import scienceworld.objects.electricalcomponent.{Battery, LightBulb, PolarizedElectricalComponent, Switch, Wire}
import scienceworld.objects.location.{Location, Room, Universe}
import scienceworld.objects.misc.Picture
import scienceworld.objects.portal.Door
import scienceworld.struct.EnvObject

import scala.util.Random

class EnvironmentMaker {

}

object EnvironmentMaker {


  def mkKitchenEnvironment(seed:Long): (EnvObject, Agent) = {
    Random.setSeed(seed)

    // Universe (object tree root)
    val universe = new Universe()

    // Sewer (for plumbing)
    val sewer = new Sewer()
    universe.addObject(sewer)

    // House
    BuildingMaker.mkRandomHouse(universe, sewer)

    // Agent
    val agent = new Agent()

    // Place in a random location
    val locations = universe.getContainedObjectsOfType[Location]().toArray.sortBy(obj => (obj.name, obj.uuid))
    val randomLocation = locations( Random.nextInt(locations.length) )

    // Normal: Random location
    randomLocation.addObject(agent)

    //## DEBUG
    //## Specific start point in environment
    //for (location <- locations) if (location.name == "workshop") location.addObject(agent)
    //for (location <- locations) if (location.name == "kitchen") location.addObject(agent)
    //for (location <- locations) if (location.name == "greenhouse") location.addObject(agent)
    //for (location <- locations) if (location.name == "outside") location.addObject(agent)
    //for (location <- locations) if (location.name == "art studio") location.addObject(agent)
    //for (location <- locations) if (location.name == "hallway") location.addObject(agent)


    // Return
    return (universe, agent)
  }

}
