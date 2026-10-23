package scienceworld.tasks.goals.specificgoals

import scienceworld.actions.{ActionLookAt, ActionRead, ActionUseDevice}
import scienceworld.objects.agent.Agent
import scienceworld.struct.EnvObject
import scienceworld.tasks.goals.{Goal, GoalReturn, GoalSequence}

import scala.util.control.Breaks._


// Success if the agent has examined an object with a specific name.
// This is evaluated by checking the agents action history.
class GoalPastActionExamineObject(objectName:String, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional
  var activatedAtStep:Int = -1   // The step that the preconditions for this action checker were met

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // NOTE: Focus object not required

    // If this is the first activation, then the preconditions have been met -- populate what step this action was activated at, so we only look at post-activation history
    if (activatedAtStep == -1) this.activatedAtStep = agent.getActionHistorySize()
    // Get history
    val actionHistory = agent.getActionHistorySince(activatedAtStep)

    var found = false
    breakable {
      for (action <- actionHistory) {
        action match {
          case a: ActionLookAt => {
            val examinedObj = a.assignments("obj")
            if ((examinedObj.name.toLowerCase == objectName.toLowerCase) || (examinedObj.getDescriptName().toLowerCase == objectName.toLowerCase)) {
              found = true
              break()
            }
          }
          case _ => {
            // Do nothing
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

class GoalPastActionUseObjectOnObject(deviceName:String, patientObjectName:String, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional
  var activatedAtStep:Int = -1   // The step that the preconditions for this action checker were met

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // NOTE: Focus object not required

    // If this is the first activation, then the preconditions have been met -- populate what step this action was activated at, so we only look at post-activation history
    if (activatedAtStep == -1) this.activatedAtStep = agent.getActionHistorySize()
    // Get history
    val actionHistory = agent.getActionHistorySince(activatedAtStep)

    var found = false
    breakable {
      for (action <- actionHistory) {
        action match {
          case a: ActionUseDevice => {
            val dName = a.assignments("device")
            val pName = a.assignments("patient")
            if ((dName.name.toLowerCase == deviceName.toLowerCase) || (pName.getDescriptName().toLowerCase == patientObjectName.toLowerCase)) {
              found = true
              break()
            }
          }
          case _ => {
            // Do nothing
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

class GoalPastActionReadObject(documentName:String, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional
  var activatedAtStep:Int = -1   // The step that the preconditions for this action checker were met

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // NOTE: Focus object not required

    // If this is the first activation, then the preconditions have been met -- populate what step this action was activated at, so we only look at post-activation history
    if (activatedAtStep == -1) this.activatedAtStep = agent.getActionHistorySize()
    // Get history
    val actionHistory = agent.getActionHistorySince(activatedAtStep)

    var found = false
    breakable {
      for (action <- actionHistory) {
        action match {
          case a: ActionRead => {
            val examinedObj = a.assignments("document")
            if ((examinedObj.name.toLowerCase == documentName.toLowerCase) || (examinedObj.getDescriptName().toLowerCase == documentName.toLowerCase)) {
              found = true
              break()
            }
          }
          case _ => {
            // Do nothing
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
