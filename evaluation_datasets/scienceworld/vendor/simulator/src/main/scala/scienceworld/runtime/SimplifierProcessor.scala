package main.scala.scienceworld.runtime

import scienceworld.objects.agent.Agent
import scienceworld.objects.location.Universe
import scienceworld.objects.portal.Portal
import scienceworld.struct.EnvObject

import scala.collection.mutable
import scala.collection.mutable.ArrayBuffer
import scala.util.control.Breaks._
import SimplifierProcessor._

// Generic
class Simplification(val label:String, val description:String) {
  var runAtInitialization:Boolean = false
  var runEachTick:Boolean = false

  def runSimplification(universe:EnvObject, agent:Agent):Boolean = {
    return false
  }

}

// Simplification: Open all doors in the environment
class SimplificationOpenDoors extends Simplification(label = SIMPLIFICATION_OPEN_DOORS, description = "All doors are open by default.") {
  runAtInitialization = true

  override def runSimplification(universe: EnvObject, agent:Agent): Boolean = {
    val allObjs = universe.getContainedObjectsAndPortalsRecursive(includeHidden = true, includePortalConnections = true)
    for (obj <- allObjs) {
      obj match {
        case x:Portal => {
          if ((x.propPortal.isDefined) && (x.propPortal.get.isOpenable)) {    // If a portal is openable
            x.propPortal.get.isOpen = true                                    // Open it
          }
        }
        case _ => {
          // do nothing
        }
      }
    }

    return true
  }

}


// Simplification: Open all containers in the environment
class SimplificationOpenContainers extends Simplification(label = SIMPLIFICATION_OPEN_CONTAINERS, description = "All containers are open by default.") {
  runAtInitialization = true

  override def runSimplification(universe: EnvObject, agent:Agent): Boolean = {
    val allObjs = universe.getContainedObjectsAndPortalsRecursive(includeHidden = true, includePortalConnections = true)
    for (obj <- allObjs) {
      obj match {
        case x:EnvObject => {
          if ((x.propContainer.isDefined) && (x.propContainer.get.isContainer) && (x.propContainer.get.isClosable)) {    // If an object is a container that's closable
            x.propContainer.get.isOpen = true                                    // Open it
          }
        }
        case _ => {
          // do nothing
        }
      }
    }

    return true
  }

}


/*
 * Action space simplifications
 * These actions do not need to be explicitly run, but are essentially flags that are checked for during action initialization
 */
class SimplificationTeleportAction extends Simplification(label = SIMPLIFICATION_TELEPORT_ACTION, description = "Adds a teleport action.") {

}

class SimplificationNoElectricalActions extends Simplification(label = SIMPLIFICATION_NO_ELECTRICAL_ACTION, description = "Remove the electrical actions, which add a large number of possible valid actions to the action space.") {

}

/*
 * Watering
 */
class SimplificationSelfWateringFlowerPots extends Simplification(label = SIMPLIFICATION_SELF_WATERING_FLOWER_POTS, description = "Flower pots are self-watering.") {

}



/*
 * Simplification Processor
 */

object SimplifierProcessor {
  val simplifications = new ArrayBuffer[Simplification]()

  val SIMPLIFICATION_TELEPORT_ACTION            = "teleportAction"
  val SIMPLIFICATION_NO_ELECTRICAL_ACTION       = "noElectricalAction"
  val SIMPLIFICATION_OPEN_DOORS                 = "openDoors"
  val SIMPLIFICATION_OPEN_CONTAINERS            = "openContainers"
  val SIMPLIFICATION_SELF_WATERING_FLOWER_POTS  = "selfWateringFlowerPots"

  // Accessors
  def addSimplification(simplification:Simplification): Unit = {
    // Check for duplicates
    for (s <- simplifications) {
      if (s.label == simplification.label) return
    }
    // Add if not a duplicate
    simplifications.append(simplification)
  }

  // Check to see if a simplification is enabled
  def isSimplificationEnabled(label:String):Boolean = {
    for (s <- simplifications) {
      if (s.label.toLowerCase == label.toLowerCase) return true
    }
    // Default return
    false
  }

  /*
   * Parsing/adding simplifications
   */

  // A CSV string with all the simplifications that should be added
  // e.g. openDoors,openContainers
  // NOTE: Clears out any simplifications currently being used
  def parseSimplificationStr(simplificationStr:String):(Boolean, String) = {
    this.simplifications.clear()    // Clear out any current simplifications
    val allSimplifications = this.getAllSimplifications()

    if (simplificationStr.length == 0) return (true, "")

    val fields = simplificationStr.toLowerCase.trim().split(",")

    for (field <- fields) {
      breakable {
        for (s <- allSimplifications) {
          if (s.label.toLowerCase == field.trim()) {
            println("Adding simplification: (" + s.label + "): " + s.description)
            this.addSimplification(s)
            break()
          }
        }

        return (false, "ERROR: Unknown simplification label: " + field)
      }
    }
    return (true, "")
  }

  /*
   * Get simplifications being used
   */
  def getSimplificationsUsed():String = {
    return simplifications.map(_.label).sorted.mkString(", ")
  }

  def getPossibleSimplifications():String = {
    return this.getAllSimplifications().map(_.label).sorted.mkString(", ")
  }

  /*
   * Run simplifications
   */
  def runSimplificationsInitialization(universe: EnvObject, agent: Agent): Boolean = {
    var successOverall = true
    for (s <- simplifications) {
      if (s.runAtInitialization) {
        println ("Running simplification: " + s.label)
        val success = s.runSimplification(universe, agent)
        if (!success) successOverall = false
      }
    }
    return successOverall
  }

  def runSimplificationsEachTick(universe: EnvObject, agent: Agent): Boolean = {
    var successOverall = true
    for (s <- simplifications) {
      if (s.runEachTick) {
        println ("Running simplification: " + s.label)
        val success = s.runSimplification(universe, agent)
        if (!success) successOverall = false
      }
    }
    return successOverall
  }


  /*
   * Helper functions
   */
  // Add all new simplifications here
  def getAllSimplifications():Array[Simplification] = {
    val out = new ArrayBuffer[Simplification]()

    out.append( new SimplificationOpenDoors() )
    out.append( new SimplificationOpenContainers() )

    out.append( new SimplificationTeleportAction() )
    out.append( new SimplificationNoElectricalActions() )

    out.append( new SimplificationSelfWateringFlowerPots() )

    return out.toArray
  }
}
