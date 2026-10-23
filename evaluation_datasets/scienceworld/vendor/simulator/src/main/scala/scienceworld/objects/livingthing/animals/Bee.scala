package scienceworld.objects.livingthing.animals

import scienceworld.objects.livingthing.LivingThing
import scienceworld.objects.livingthing.plant.{Flower, Pollen}
import scienceworld.objects.location.Location
import scienceworld.processes.lifestage.{AdultForeverLifeStage, TortoiseLifeStage}
import scienceworld.properties.{LifePropertiesBee, LifePropertiesGiantTortoise}
import scienceworld.struct.EnvObject._

import scala.util.Random


class WanderingAnimal extends Animal {
  this.name = "wandering animal"

  /*
   * Actions
   */

  def moveToNewLocation(): Boolean = {
    // println ("### MOVE TO NEW LOCATION")
    // Step 1: Find a list of possible locations that are connected
    if (this.getContainer().isEmpty) return false
    val currentLocation = this.getContainer().get

    val passablePortals = currentLocation.getPortals().filter(_.isCurrentlyPassable()).toArray.sortBy(_.uuid)
    // println ("### Passable Portals: " + passablePortals.map(_.name).mkString(", "))

    if (passablePortals.size == 0) {
      // There do not appear to be any portals here. Check if we're currently in an open container.  If we are, then exit out of the container?

      // If we're already in a Location, don't try to jump out of it through going to the parent container
      if (currentLocation.isInstanceOf[Location]) return false

      if ((currentLocation.propContainer.isDefined) && (currentLocation.propContainer.get.isOpen)) {
        val parentContainer = currentLocation.getContainerRecursiveOfType[Location]()         // Make sure the container is a 'Location'
        // println ("### Possible parent container: " + parentContainer)
        if (parentContainer.isEmpty) return false
        // Move to parent container
        // println ("### " + this.name + " MOVING TO PARENT CONTAINER: " + parentContainer.get.name)
        parentContainer.get.addObject( this )
      }
      // println ("out")

      // No portals, and not in an open container
      return false
    }

    // Step 2: Pick a random location
    val randIdx = Random.nextInt(passablePortals.size)
    val moveLocation = passablePortals(randIdx).getConnectsTo(perspectiveContainer = currentLocation)

    // Step 2B: Move to that random location
    // println ("### " + this.name + " MOVING TO PARENT CONTAINER: " + moveLocation.get.name)
    moveLocation.get.addObject( this )

    // Return true
    return true
  }


  /*
   * Standard methods
   */

  override def tick():Boolean = {

    super.tick()
  }

  override def getReferents(): Set[String] = {
    Set("living thing", "organism", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + ". ")
    if (mode == MODE_DETAILED) {
      // Extended detail
    }

    os.toString
  }

}




class Bee extends WanderingAnimal {
  this.name = "bee"

  this.propLife = Some( new LifePropertiesBee() )
  lifecycle = Some( AdultForeverLifeStage.mkAdultForeverLifeCycle(this) )

  val maxPollen:Int = 5

  // Movable: not movable except by other means (e.g. catching in a net?)

  /*
   * Actions
   */

  // Move the bee into a flower, if one is in the same container
  def moveIntoFlower():Boolean = {
    // println ("### MOVE INTO FLOWER")
    // Step 1: Find a list of possible locations that are connected
    if (this.getContainer().isEmpty) return false
    val currentLocation = this.getContainer().get

    // Check if there are any flowers
    val flowers = currentLocation.getContainedAccessibleObjectsOfType[Flower]().toArray.sortBy(_.uuid)
    // println ("flowers: " + flowers.mkString(", "))
    // println ("accessible objects: " + currentLocation.getContainedAccessibleObjects().map(_.name).mkString(", ") )

    if (flowers.size == 0) return false

    // Pick random flower
    val randIdx = Random.nextInt( flowers.size )
    val flower = flowers(randIdx)

    // Move into flower
    flower.addObject( this )

    // Return success
    return true
  }

  // If the bee is in the same container as pollen, and doesn't already have maxPollen, then collect that pollen
  def collectPollen(): Boolean = {
    // println ("### COLLECT POLLEN")

    // Step 1: Find a list of possible locations that are connected
    if (this.getContainer().isEmpty) return false
    val currentLocation = this.getContainer().get

    // Check if the bee already has a maximum amount of pollen
    if (this.getContainedAccessibleObjectsOfType[Pollen]().size > this.maxPollen) return false

    // Check if there is any pollen
    val pollens = currentLocation.getContainedObjectsOfType[Pollen]().toArray.sortBy(_.uuid)
    if (pollens.size == 0) return false

    // Pick random pollen
    val randIdx = Random.nextInt( pollens.size )
    val pollen = pollens(randIdx)

    // Move into bee
    this.addObject( pollen )

    // Return success
    return true
  }


  def isInFlower():Boolean = {
    if ((this.getContainer().isDefined) && (this.getContainer().get.isInstanceOf[Flower])) return true
    // Otherwise
    return false
  }


  /*
   * Standard methods
   */

  override def tick():Boolean = {
    // Do not continue if this tick was already processed (i.e. if the bee was in a different location this iteration)
    if (this.wasTickProcessed()) return false

    // println ("### " + this.name + ": TICK")

    // Do actions
    if (this.isInFlower()) {
      // If the bee is in a flower
      val randAction = Random.nextInt(2)
      if (randAction == 0) {
        this.collectPollen()
      } else {
        this.moveToNewLocation()
      }

    } else {
      // If the bee is outside a flower
      val randAction = Random.nextInt(2)
      if (randAction == 1) {
        this.moveIntoFlower()
      } else {
        this.moveToNewLocation()
      }
    }


    super.tick()
  }

  override def getReferents(): Set[String] = {
    Set("living thing", "organism", this.name, this.propLife.get.lifeformType, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder


    // If dead, simplify the name
    if (propLife.get.isDead) {
      os.append("a dead " + this.getDescriptName())
      return os.toString()
    }

    // If alive, give a verbose name
    os.append("a " + this.getDescriptName())

    if (propLife.get.isSickly) os.append(" (that looks unwell)")

    if (mode == MODE_DETAILED) {
      // Extended detail
      if (this.getContainedAccessibleObjectsOfType[Pollen]().size > 0) {
        os.append(", that is covered in pollen")
      }
    }

    os.toString
  }

}
