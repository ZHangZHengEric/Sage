package scienceworld.tasks.goals.specificgoals

import scienceworld.objects.agent.Agent
import scienceworld.struct.EnvObject
import scienceworld.tasks.goals.{Goal, GoalReturn, GoalSequence}



class GoalActivateDevice(deviceName:String = "", sameAsLastDevice:Boolean = false, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Check for material properties to be defined
    if (!obj.get.propDevice.isDefined) return GoalReturn.mkSubgoalUnsuccessful()

    if (obj.get.name != deviceName) return GoalReturn.mkSubgoalUnsuccessful()

    // Check that the focus object of this step is the same as the focus object of the previous step
    if (sameAsLastDevice) {
      if (gs.getLastSatisfiedObject().isDefined) {
        if (gs.getLastSatisfiedObject().get != obj.get) return GoalReturn.mkSubgoalUnsuccessful()
      }
    }

    // Check for state of matter to NOT be a specific value
    //println ("obj.propMaterial.get.stateOfMatter: " + obj.propMaterial.get.stateOfMatter)
    if (obj.get.propDevice.get.isActivated == true) {
      this.satisfiedWithObject = obj
      return GoalReturn.mkSubgoalSuccess()
    }
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}


class GoalDeactivateDevice(deviceName:String = "", sameAsLastDevice:Boolean = false, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Check for material properties to be defined
    if (!obj.get.propDevice.isDefined) return GoalReturn.mkSubgoalUnsuccessful()

    if (obj.get.name != deviceName) return GoalReturn.mkSubgoalUnsuccessful()

    // Check that the focus object of this step is the same as the focus object of the previous step
    if (sameAsLastDevice) {
      if (gs.getLastSatisfiedObject().isDefined) {
        if (gs.getLastSatisfiedObject().get != obj.get) return GoalReturn.mkSubgoalUnsuccessful()
      }
    }

    // Check for state of matter to NOT be a specific value
    //println ("obj.propMaterial.get.stateOfMatter: " + obj.propMaterial.get.stateOfMatter)
    if (obj.get.propDevice.get.isActivated == false) {
      this.satisfiedWithObject = obj
      return GoalReturn.mkSubgoalSuccess()
    }
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}
