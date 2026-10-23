package scienceworld.tasks

import scienceworld.objects.agent.Agent
import scienceworld.struct.EnvObject

import scala.collection.mutable.ArrayBuffer
import scala.util.Random
import scala.util.control.Breaks.{break, breakable}

// Base class
trait TaskModifier {

  // Run this modifier
  def runModifier(universe:EnvObject, agent:Agent):Boolean

  // Helper function: Find all objects in the environment with a given name
  def findObjectsWithName(queryName:String, envRoot:EnvObject):Set[EnvObject] = {
    val allObjects = envRoot.getContainedObjectsAndPortalsRecursive()
    val queryObjects = allObjects.filter(_.name == queryName)
    return queryObjects
  }

}

// An example of a specific object required for a task:
// (a) it's name,
// (b) if it needs to be generated (and isn't just found in the environment naturally), an example instance of it
// (c) if generation is required, what room to generate it in (set to "" for n/a)
// (d) if generation if required, what container name(s) are valid to place it into (e.g. "desk", "table").  If blank, it will be placed in the root container (e.g. the 'floor')
// (e) generateNear: If non-zero, it will generate the object within 'generateNear' steps of the original location.  e.g. if the generation location is 'kitchen', and generateNear is 2, then the object could be generated in (e.g.) the hallway or bathroom, but not a far-off location.
class TaskObject(val name:String, val exampleInstance:Option[EnvObject], val roomToGenerateIn:String, val possibleContainerNames:Array[String], val generateNear:Int=0, val disableRecursiveCheck:Boolean = false, forceAdd:Boolean = false) extends TaskModifier {
  // Does this task object need to be generated in the environment?
  val needsToBeGenerated:Boolean = exampleInstance.isDefined

  // Add a given object to a given room.
  // TODO: Doesn't currently use 'generateNear' parameter.
  override def runModifier(universe: EnvObject, agent: Agent): Boolean = {
    println ("#### TaskObject: Running for (" + name + "), roomToGenerateIn(" + roomToGenerateIn + ")")

    // Step 1: Check to see if the object is marked as required to be generated
    if (!needsToBeGenerated) {
      println ("### TaskObject: Object (" + name + ") does not need to be generated.")
      return true
    }

    // Step 2: Check to see if the object already exists in the environment
    val allObjects:Set[EnvObject] = universe.getContainedObjectsAndPortalsRecursive()
    for (obj <- allObjects) {
      if (obj.name == roomToGenerateIn) {
        println ("Found room (" + roomToGenerateIn + ")")
        // First, check to see if the object already exists
        if ((possibleContainerNames.length == 0) || ((possibleContainerNames.length == 1) && (possibleContainerNames(0).length == 0))) {
          // CASE 1: Just generate in the main container
          var containedObjects = Set.empty[EnvObject]
          if (disableRecursiveCheck) {
            containedObjects = obj.getContainedObjects()
          } else {
            containedObjects = obj.getContainedObjectsRecursive()
          }

          for (cObj <- containedObjects) {
            if (cObj.name == name) {
              // An existing object with this name has been found -- exit
              println("### TaskObject: Existing object with that name (" + name + ") has been found in container (" + obj.name + ")")
              if (!forceAdd) return true
            }
          }
        } else {
          // CASE 2: Generate in a sub-container of the main container
          val containedObjects = obj.getContainedObjects()

          for (cObj <- containedObjects) {
            if (possibleContainerNames.contains(cObj.name)) {
              // A relevant container has been found -- check all the objects in the container to see if an existing one has the same name
              var containedObjects1 = Set.empty[EnvObject]
              if (disableRecursiveCheck) {
                containedObjects1 = cObj.getContainedObjects()
              } else {
                containedObjects1 = cObj.getContainedObjectsRecursive()
              }

              for (ccObj <- containedObjects1) {
                if (ccObj.name == name) {
                  // An existing object with this name has been found -- exit
                  println("### TaskObject: Existing object with that name (" + name + ") has been found in container (" + ccObj.name + ")")
                  if (!forceAdd) return true
                }
              }
            }
          }
        }

        // If we reach here, the object needs to be generated
        if (exampleInstance.isEmpty) throw new RuntimeException("ERROR: Trying to generate TaskObject, but exampleInstance is not defined.")
        if ((possibleContainerNames.length == 0) || ((possibleContainerNames.length == 1) && (possibleContainerNames(0).length == 0))) {
          // CASE 1: Just generate in the main container
          obj.addObject( exampleInstance.get )
          println("### TaskObject: Adding object (" + exampleInstance.get.name + ") to (" + obj.name + ")")
        } else {
          // CASE 2: Generate in a sub-container of the main container
          val containedObjects = Random.shuffle( obj.getContainedObjectsRecursive().toArray.sortBy(_.uuid).toList )     // Since the order of a set is not guaranteed, this tries to keep it the same between runs (by sorting) so the generation is deterministic

          for (cObj <- containedObjects) {
            if (possibleContainerNames.contains(cObj.name)) {
              // Add to this container
              println("### TaskObject: Adding object (" + exampleInstance.get.name + ") to (" + cObj.name + ")")
              cObj.addObject( exampleInstance.get )
              return true
            }
          }

          // If we reach here, then no valid 'possibleContainer' was found
          println ("ERROR: No valid possibleContainer (" + possibleContainerNames.mkString(", ") + ") was found in (" + obj.name + ").")
          // (But, we'll allow it to keep going, just in case there is another container named 'roomToGenerateIn' in the environment)
        }
        return true
      }
    }

    println("### TaskObject: ERROR: Reached the end without adding an object.")
    return false
  }


}


// Disables a device, with a given name, in a given room.
class TaskDisable(val name:String, val roomIn:Array[String]) extends TaskModifier {

  // Disable all devices with a given name, that are contained within any of the container listed in 'room'.  Looks recursively in containers.
  override def runModifier(universe: EnvObject, agent: Agent): Boolean = {
    // Step 1: Look for the object(s) to disable
    val objsToDisable = new ArrayBuffer[EnvObject]

    // First, look for all objects in the universe with that name
    val objsWithName = this.findObjectsWithName(name, universe)
    // Then, see if those objects are also in a relevant container
    for (obj <- objsWithName) {
      val containers = obj.getContainersRecursive()                   // Get all containers (down to the world tree root) that this object is in
      breakable {
        for (container <- containers) {
          if (roomIn.contains(container.name)) {                      // If one of the containers it's in is listed in the 'roomIn' find list, then add it to the list of devices to disable
            objsToDisable.append(obj)
            break()
          }
        }
      }
    }

    // Step 2: Disable objects
    var numDisabled:Int = 0
    for (obj <- objsToDisable) {
      if (obj.propDevice.isDefined) {
        obj.propDevice.get.isBroken = true      // Disable the device
        println("### TaskDisable: Disabled device (" + obj.name + ") in (" + obj.getContainer().get.name + ").")
        numDisabled += 1
      }
    }

    // Step 3: Return true if we successfully disabled at least one device
    if (numDisabled > 0) {
      return true
    }
    return false
  }

}


// Storage class for a key
class TaskValueStr(val key:String, val value:String) extends TaskModifier {
  override def runModifier(universe: EnvObject, agent: Agent): Boolean = {
    // Nothing to do -- this modifier just stores a key/value pair for task setup (e.g. conveying a correct answer for a goal)
    true
  }
}

class TaskValueBool(val key:String, val value:Boolean) extends TaskModifier {
  override def runModifier(universe: EnvObject, agent: Agent): Boolean = {
    // Nothing to do -- this modifier just stores a key/value pair for task setup (e.g. conveying a correct answer for a goal)
    true
  }
}

class TaskValueDouble(val key:String, val value:Double) extends TaskModifier {
  override def runModifier(universe: EnvObject, agent: Agent): Boolean = {
    // Nothing to do -- this modifier just stores a key/value pair for task setup (e.g. conveying a correct answer for a goal)
    true
  }
}

class TaskValueInt(val key:String, val value:Int) extends TaskModifier {
  override def runModifier(universe: EnvObject, agent: Agent): Boolean = {
    // Nothing to do -- this modifier just stores a key/value pair for task setup (e.g. conveying a correct answer for a goal)
    true
  }
}
