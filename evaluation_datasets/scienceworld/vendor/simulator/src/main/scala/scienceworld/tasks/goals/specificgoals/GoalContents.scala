package scienceworld.tasks.goals.specificgoals

import scienceworld.objects.agent.Agent
import scienceworld.objects.livingthing.LivingThing
import scienceworld.objects.livingthing.animals.Animal
import scienceworld.objects.livingthing.plant.Plant
import scienceworld.struct.EnvObject
import scienceworld.tasks.goals.{Goal, GoalReturn, GoalSequence}

import scala.util.control.Breaks.{break, breakable}

/*
 * Focus on specific classes of objects
 */

class GoalFocusOnLivingThing(_isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    if (obj.get.isInstanceOf[LivingThing]) {
      this.satisfiedWithObject = obj
      return GoalReturn.mkSubgoalSuccess()
    }

    // If we've focused on something different, the task has failed
    return GoalReturn.mkTaskFailure()
  }

}

class GoalFocusOnNonlivingThing(_isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    if (!obj.get.isInstanceOf[LivingThing]) {
      // Also check that the thing that's being focused on is movable
      if ((obj.get.propMoveable.isDefined) && (obj.get.propMoveable.get.isMovable)) {
        this.satisfiedWithObject = obj
        return GoalReturn.mkSubgoalSuccess()
      } else {
        return GoalReturn.mkSubgoalUnsuccessful()     // Just go unsuccessful, not full on fail, if they focus on an unmovable object (for reward shaping)
      }
    }

    // If we've focused on something different, the task has failed
    return GoalReturn.mkTaskFailure()
  }

}



class GoalFocusOnAnimal(_isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    if (obj.get.isInstanceOf[Animal]) {
      this.satisfiedWithObject = obj
      return GoalReturn.mkSubgoalSuccess()
    }

    // If we've focused on something different, the task has failed
    return GoalReturn.mkTaskFailure()
  }

}


class GoalFocusOnPlant(_isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    if (obj.get.isInstanceOf[Plant]) {
      this.satisfiedWithObject = obj
      return GoalReturn.mkSubgoalSuccess()
    }

    // If we've focused on something different, the task has failed
    return GoalReturn.mkTaskFailure()
  }

}





/*
 * Check to see if the focus object has been placed in a specific container
 */

// Object must be in the container
// If the focus object is in one of the containers listed in 'failureContainers', then it causes task failure.
class GoalObjectInDirectContainer(containerName:String = "", failureContainers:List[EnvObject] = List.empty[EnvObject], _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Check that the focus object of this step is the same as the focus object of the previous step
    if (gs.getLastSatisfiedObject().isDefined) {
      if (gs.getLastSatisfiedObject().get != obj.get) return GoalReturn.mkSubgoalUnsuccessful()
    }

    // Check if the object is in one of the incorrect (failure) containers that would cause task failure
    if (obj.get.getContainer().isDefined) {
      for (failContainer <- failureContainers) {
        if (obj.get.getContainer().get.name == failContainer.name) return GoalReturn.mkTaskFailure()
      }
    }

    // Check that the object's container name is set to the desired container
    if (obj.get.getContainer().isEmpty) return GoalReturn.mkSubgoalUnsuccessful()
    if (obj.get.getContainer().get.name.toLowerCase != containerName.toLowerCase) return GoalReturn.mkSubgoalUnsuccessful()


    // If we reach here, the condition is satisfied
    this.satisfiedWithObject = obj
    return GoalReturn.mkSubgoalSuccess()
  }

}


// Object could be in the container, or a container within that container
// If the focus object is in one of the containers listed in 'failureContainers', then it causes task failure.
class GoalObjectInContainer(containerName:String = "", failureContainers:List[EnvObject] = List.empty[EnvObject], _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    val MAX_STEPS:Int = 20
    var numSteps:Int = 0

    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Check that the focus object of this step is the same as the focus object of the previous step
    if (gs.getLastSatisfiedObject().isDefined) {
      if (gs.getLastSatisfiedObject().get != obj.get) return GoalReturn.mkSubgoalUnsuccessful()
    }

    // Check if the object is in one of the incorrect (failure) containers that would cause task failure
    if (obj.get.getContainer().isDefined) {
      for (failContainer <- failureContainers) {
        // First, start at the direct container
        var objContainer:Option[EnvObject] = obj.get.getContainer()
        // Also check recursive containers by recusing down to object tree root
        numSteps = 0
        while (objContainer.isDefined && (numSteps < MAX_STEPS)) {
          if (objContainer.get.name == failContainer.name) {
            return GoalReturn.mkTaskFailure()
          }
          objContainer = objContainer.get.getContainer()
          numSteps += 1
        }
      }
    }

    // Check that the object's container name is set to the desired container
    var container:Option[EnvObject] = obj.get.getContainer()
    numSteps = 0
    while (container.isDefined && (numSteps < MAX_STEPS)) {
      // Check to see if this container is the query container
      if (container.get.name.toLowerCase == containerName.toLowerCase()) {
        this.satisfiedWithObject = obj
        return GoalReturn.mkSubgoalSuccess()
      }

      // If not, recurse
      container = container.get.getContainer()
      numSteps += 1                               // This solves a potential issue with an infinite loop if bugs happen where something ends up in something else.
    }

    // If we reach here, the condition was not satisfied
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}

class GoalObjectInContainerByName(containerName:String = "", failureContainers:List[String] = List.empty[String], _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    val MAX_STEPS:Int = 20
    var numSteps:Int = 0

    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Check that the focus object of this step is the same as the focus object of the previous step
    if (gs.getLastSatisfiedObject().isDefined) {
      if (gs.getLastSatisfiedObject().get != obj.get) return GoalReturn.mkSubgoalUnsuccessful()
    }

    // Check if the object is in one of the incorrect (failure) containers that would cause task failure
    if (obj.get.getContainer().isDefined) {
      for (failContainer <- failureContainers) {
        // First, start at the direct container
        var objContainer:Option[EnvObject] = obj.get.getContainer()
        // Also check recursive containers by recusing down to object tree root
        numSteps = 0
        while (objContainer.isDefined && (numSteps < MAX_STEPS)) {
          if (objContainer.get.name == failContainer) {
            return GoalReturn.mkTaskFailure()
          }
          objContainer = objContainer.get.getContainer()
          numSteps += 1
        }
      }
    }

    // Check that the object's container name is set to the desired container


    var container:Option[EnvObject] = obj.get.getContainer()
    numSteps = 0
    while (container.isDefined && (numSteps < MAX_STEPS)) {
      // Check to see if this container is the query container
      if (container.get.name.toLowerCase == containerName.toLowerCase()) {
        this.satisfiedWithObject = obj
        return GoalReturn.mkSubgoalSuccess()
      }

      // If not, recurse
      container = container.get.getContainer()
      numSteps += 1                               // This solves a potential issue with an infinite loop if bugs happen where something ends up in something else.
    }

    // If we reach here, the condition was not satisfied
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}


class GoalContainerOpen(containerName:String = "", _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
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
        if ((vObj.name.toLowerCase == containerName.toLowerCase) || (vObj.getDescriptName().toLowerCase == containerName.toLowerCase)) {
          if ((vObj.propContainer.isDefined) && (vObj.propContainer.get.isOpen)) {
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
    return GoalReturn.mkSubgoalUnsuccessful()  }

}
