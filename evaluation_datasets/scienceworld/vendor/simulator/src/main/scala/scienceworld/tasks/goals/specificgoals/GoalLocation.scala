package scienceworld.tasks.goals.specificgoals

import scienceworld.objects.agent.Agent
import scienceworld.objects.livingthing.LivingThing
import scienceworld.objects.portal.Door
import scienceworld.struct.EnvObject
import scienceworld.tasks.goals.{Goal, GoalReturn, GoalSequence}
import scala.util.control.Breaks._


// Success when an agent moves to the specified location(/container)
class GoalMoveToLocation(locationToBeIn:String, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // NOTE: Focus object not required

    // If agent is not in a container, do not continue evaluation
    if (agent.getContainer().isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // If the agent is in the correct location, then success
    val agentLocation = agent.getContainer().get.name
    if (agentLocation == locationToBeIn) {
      return GoalReturn.mkSubgoalSuccess()
    }

    // Otherwise
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}

// Success when an agent moves to a different location than it started in
class GoalMoveToNewLocation(_isOptional:Boolean = false, unlessInLocation:String = "", description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  var startingLocation:Option[String] = None
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // NOTE: Focus object not required

    // If agent is not in a container, do not continue evaluation
    if (agent.getContainer().isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Get agent location
    val agentLocation = agent.getContainer().get.name

    // Sometimes the agent might initialize in the correct location.  Have a special case for this, so the agent doesn't get rewarded for moving away.
    if (agentLocation == unlessInLocation) return GoalReturn.mkSubgoalSuccess()

    // First initialization: Keep track of starting location
    if (startingLocation.isEmpty) {
      gs.setKey("startingLocation", agentLocation)      // PJ: Added, just in case we need this information later
      startingLocation = Some(agentLocation)
      return GoalReturn.mkSubgoalUnsuccessful()
    }

    // If the agent is a different location than the starting location, then success
    if (agentLocation != startingLocation.get) {
      return GoalReturn.mkSubgoalSuccess()
    }

    // Otherwise
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}


// Success when an agent is in a room with an open door (principally, by opening that door)
class GoalInRoomWithOpenDoor(_isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // NOTE: Focus object not required

    // If agent is not in a container, do not continue evaluation
    if (agent.getContainer().isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Get agent location
    val agentLocation = agent.getContainer().get
    val portals = agentLocation.getPortals()

    var isAtLeastOneOpenDoor:Boolean = false
    for (portal <- portals) {
      //println ("Checking: " + portal.toStringMinimal())
      portal match {
        case d:Door => {
          if (d.isCurrentlyPassable()) {
            //print("\tIS OPEN!")
            isAtLeastOneOpenDoor = true
          }
        }
      }
    }

    // First initialization: Keep track of starting location
    if (isAtLeastOneOpenDoor) {
      return GoalReturn.mkSubgoalSuccess()
    }

    // Otherwise
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}

// Success when an agent is in a room with a particular object being visible.
// Searches object names, object descript names, and object material names.
class GoalInRoomWithObject(objectName:String, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // NOTE: Focus object not required

    // If agent is not in a container, do not continue evaluation
    if (agent.getContainer().isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Get agent location
    val agentLocation = agent.getContainer().get
    val visibleObjects = agentLocation.getContainedObjectsAndPortalsRecursive(includeHidden = false, includePortalConnections = false)

    var found:Boolean = false
    breakable {
      for (obj <- visibleObjects) {
        if ((obj.name.toLowerCase == objectName.toLowerCase) ||
            (obj.getDescriptName().toLowerCase == objectName)) {
            //((obj.propMaterial.isDefined) && (obj.propMaterial.get.substanceName == objectName))) {
          found = true
          break
        }
      }
    }

    // First initialization: Keep track of starting location
    if (found) {
      return GoalReturn.mkSubgoalSuccess()
    }

    // Otherwise
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}


// Success when an agent is in a room with a particular object being visible.
// Searches object names, object descript names, and object material names.
class GoalObjectsInSingleContainer(objectNames:Array[String], _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // NOTE: Focus object not required

    // If agent is not in a container, do not continue evaluation
    if (agent.getContainer().isEmpty) return GoalReturn.mkSubgoalUnsuccessful()
    // If no objects to find, then do not continue evaluation
    if (objectNames.size == 0) return GoalReturn.mkSubgoalUnsuccessful()

    // Get agent location
    val agentLocation = agent.getContainer().get
    val visibleObjects = agentLocation.getContainedObjectsAndPortalsRecursive(includeHidden = false, includePortalConnections = false)

    var found:Boolean = false
    breakable {
      for (obj <- visibleObjects) {
        val contents = obj.getContainedObjects(includeHidden = false)
        //println("Obj: " + obj.name + "\t contents: " + contents.map(_.name).mkString(", "))
        if (contents.size == objectNames.size) {
          //println("\tChecking")
          var success:Boolean = true
          // Check contents
          for (cObj <- contents) {
            if (objectNames.contains(cObj.name) || objectNames.contains(cObj.getDescriptName())) {
              // So far, so good

            } else {
              success = false
            }
          }

          //println("\tSuccess:" + success)
          if (success) {
            found = true
            break()
          }

        }
      }
    }

    // First initialization: Keep track of starting location
    if (found) {
      return GoalReturn.mkSubgoalSuccess()
    }

    // Otherwise
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}


// Success when an agent stays in a specific location for a period of time
class GoalStayInLocation(locationToBeIn:String, minSteps:Int = 0, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional
  var numTicksInLocation:Int = 0

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // NOTE: Focus object not required

    // If agent is not in a container, do not continue evaluation
    if (agent.getContainer().isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // If the agent is in the correct location
    val agentLocation = agent.getContainer().get.name
    if (agentLocation == locationToBeIn) {
      // Keep track of how long in this location
      numTicksInLocation += 1
      // If in location past the threshold, then success
      if (numTicksInLocation >= minSteps) return GoalReturn.mkSubgoalSuccess()
    } else {
      // Reset location count
      numTicksInLocation = 0
    }

    // Otherwise
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}

class GoalSpecificObjectInDirectContainer(containerName:String = "", validObjectNames:Array[String], _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // NOTE: Focus object not required

    // If agent is not in a container, do not continue evaluation
    if (agent.getContainer().isEmpty) return GoalReturn.mkSubgoalUnsuccessful()
    // If no objects to find, then do not continue evaluation
    if (validObjectNames.size == 0) return GoalReturn.mkSubgoalUnsuccessful()

    // Get agent location
    val agentLocation = agent.getContainer().get
    val visibleObjects = agentLocation.getContainedObjectsAndPortalsRecursive(includeHidden = false, includePortalConnections = false)

    var found:Boolean = false
    breakable {
      for (vObj <- visibleObjects) {
        //println("# " + vObj.name + " (" + containerName + ")")
        if ((vObj.name.toLowerCase == containerName.toLowerCase) || (vObj.getDescriptName().toLowerCase == containerName.toLowerCase)) {
          //println ("### Found container: " + vObj.name )
          val contents = vObj.getContainedObjects(includeHidden = false)
          //println("Contents: " + contents.mkString(", "))
          //println("Checking for " + validObjectNames.mkString(", "))
          for (cObj <- contents) {
            if (validObjectNames.contains(cObj.name) || validObjectNames.contains(cObj.getDescriptName())) {
              //println("\t CONTAINS")
              found = true
              break()
            }
          }
        }
      }
    }

    // First initialization: Keep track of starting location
    if (found) {
      return GoalReturn.mkSubgoalSuccess()
    }

    // Otherwise
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}

class GoalActivateDeviceWithName(deviceName:String, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // NOTE: Focus object not required

    // If agent is not in a container, do not continue evaluation
    if (agent.getContainer().isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Get agent location
    val agentLocation = agent.getContainer().get
    val visibleObjects = agentLocation.getContainedObjectsAndPortalsRecursive(includeHidden = false, includePortalConnections = false)

    var found:Boolean = false
    breakable {
      for (vObj <- visibleObjects) {
        if ((vObj.name.toLowerCase == deviceName.toLowerCase) || (vObj.getDescriptName().toLowerCase == deviceName.toLowerCase)) {
          if ((vObj.propDevice.isDefined) && (vObj.propDevice.get.isActivated)) {
            found = true
            break()
          }
        }
      }
    }

    // First initialization: Keep track of starting location
    if (found) {
      return GoalReturn.mkSubgoalSuccess()
    }

    // Otherwise
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}

class GoalDeactivateDeviceWithName(deviceName:String, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // NOTE: Focus object not required

    // If agent is not in a container, do not continue evaluation
    if (agent.getContainer().isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Get agent location
    val agentLocation = agent.getContainer().get
    val visibleObjects = agentLocation.getContainedObjectsAndPortalsRecursive(includeHidden = false, includePortalConnections = false)

    var found:Boolean = false
    breakable {
      for (vObj <- visibleObjects) {
        if ((vObj.name.toLowerCase == deviceName.toLowerCase) || (vObj.getDescriptName().toLowerCase == deviceName.toLowerCase)) {
          if ((vObj.propDevice.isDefined) && (!vObj.propDevice.get.isActivated)) {
            found = true
            break()
          }
        }
      }
    }

    // First initialization: Keep track of starting location
    if (found) {
      return GoalReturn.mkSubgoalSuccess()
    }

    // Otherwise
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}
