package scienceworld.tasks.goals.specificgoals

import scienceworld.objects.agent.Agent
import scienceworld.struct.EnvObject
import scienceworld.tasks.goals.{Goal, GoalReturn, GoalSequence}

import scala.util.control.Breaks.{break, breakable}

class GoalTemperatureOnFire(objectName:String = "", _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {

    // If agent is not in a container, do not continue evaluation
    if (agent.getContainer().isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Get agent location
    val agentLocation = agent.getContainer().get
    val visibleObjects = agentLocation.getContainedObjectsAndPortalsRecursive(includeHidden = false, includePortalConnections = false)

    var found:Boolean = false
    breakable {
      for (vObj <- visibleObjects) {
        //println("# " + vObj.name + " (" + containerName + ")")
        if ((vObj.name.toLowerCase == objectName.toLowerCase) || (vObj.getDescriptName().toLowerCase == objectName.toLowerCase)) {
          if ((vObj.propMaterial.isDefined) && (vObj.propMaterial.get.isCombusting)) {
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

class GoalTemperatureIncrease(minTempIncreaseC:Double = 1.0, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional
  var initialTemperature:Double = -999.0f

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // If an object does not have a defined temperature, return unsuccessful
    if (obj.get.propMaterial.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()


    val curTemp = obj.get.propMaterial.get.temperatureC

    // Store initial temperature on first check
    if (this.initialTemperature == -999.0f) {
      this.initialTemperature = obj.get.propMaterial.get.temperatureC
    }

    // Check if temperature has risen above threshold
    val threshTemp = this.initialTemperature + minTempIncreaseC
    if (curTemp >= threshTemp) {
      return GoalReturn.mkSubgoalSuccess()
    }

    // Otherwise
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}

class GoalTemperatureDecrease(minTempDecreaseC:Double = 1.0, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional
  var initialTemperature:Double = -999.0f

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // If an object does not have a defined temperature, return unsuccessful
    if (obj.get.propMaterial.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()


    val curTemp = obj.get.propMaterial.get.temperatureC

    // Store initial temperature on first check
    if (this.initialTemperature == -999.0f) {
      this.initialTemperature = obj.get.propMaterial.get.temperatureC
    }

    // Check if temperature has risen above threshold
    val threshTemp = this.initialTemperature - minTempDecreaseC
    if (curTemp <= threshTemp) {
      return GoalReturn.mkSubgoalSuccess()
    }

    // Otherwise
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}
