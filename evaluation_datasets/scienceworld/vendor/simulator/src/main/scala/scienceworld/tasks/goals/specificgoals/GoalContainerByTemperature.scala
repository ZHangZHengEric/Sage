package scienceworld.tasks.goals.specificgoals

import scienceworld.objects.agent.Agent
import scienceworld.struct.EnvObject
import scienceworld.tasks.goals.{Goal, GoalReturn, GoalSequence}


class GoalContainerByTemperature(tempThreshold:Double, containerNameAbove:String = "", containerNameBelow:String = "", _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Check that the focus object of this step is the same as the focus object of the previous step
    if (gs.getLastSatisfiedObject().isDefined) {
      if (gs.getLastSatisfiedObject().get != obj.get) return GoalReturn.mkSubgoalUnsuccessful()
    }

    // Get the object's current temperature
    if (obj.get.propMaterial.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()
    val objTemp = obj.get.propMaterial.get.temperatureC

    // Get the object's current container
    val curContainer = obj.get.getContainer()
    if (curContainer.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // If the container is not one of the two answer containers, then exit
    if ((curContainer.get.name != containerNameAbove) && (curContainer.get.name != containerNameBelow)) return GoalReturn.mkSubgoalUnsuccessful()

    // Success conditions
    if ((curContainer.get.name == containerNameAbove) && (objTemp >= tempThreshold)) {
      // Above temp container
      this.satisfiedWithObject = obj
      return GoalReturn.mkSubgoalSuccess()

    }
    if ((curContainer.get.name == containerNameBelow) && (objTemp <= tempThreshold)) {
      // Below temp container
      this.satisfiedWithObject = obj
      return GoalReturn.mkSubgoalSuccess()
    }

    // If we reach here, then the object is in one of the two answer containers, but not the correct one.
    return GoalReturn.mkTaskFailure()
  }

}
