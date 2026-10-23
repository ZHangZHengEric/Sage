package scienceworld.tasks.goals.specificgoals

import scienceworld.objects.agent.Agent
import scienceworld.objects.livingthing.LivingThing
import scienceworld.struct.EnvObject
import scienceworld.tasks.goals.{Goal, GoalReturn, GoalSequence}
import scala.util.control.Breaks._

// Object must be in the container
class GoalLifeStage(lifeFormType:String = "", lifeStageName:String = "", sameAsLastObj:Boolean = true, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Check that the focus object of this step is the same as the focus object of the previous step
    if (sameAsLastObj) {
      if (gs.getLastSatisfiedObject().isDefined) {
        if (gs.getLastSatisfiedObject().get != obj.get) return GoalReturn.mkSubgoalUnsuccessful()
      }
    }

    // Check that this is the correct life form type.  (Note, disabled if lifeformType is empty string)
    if (lifeFormType.length > 0) {
      if ((obj.get.propLife.isDefined) && (obj.get.propLife.get.lifeformType != lifeFormType)) {
        return GoalReturn.mkSubgoalUnsuccessful()
      }
    }

    // Check that the object is in a given life stage
    obj.get match {
      case x:LivingThing => {
        if (x.lifecycle.isDefined) {
          val curLifeStage = x.lifecycle.get.getCurStageName()
          if (curLifeStage.toLowerCase == lifeStageName.toLowerCase) {
            // If we reach here, the condition is satisfied
            this.satisfiedWithObject = obj
            return GoalReturn.mkSubgoalSuccess()
          } else {
            return GoalReturn.mkSubgoalUnsuccessful()
          }
        }
      }
      case _ => {
        return GoalReturn.mkSubgoalUnsuccessful()
      }
    }

    return GoalReturn.mkSubgoalUnsuccessful()
  }

}

// Searches for a particular life form, at a particular life stage, anywhere that's visible to the agent.
// Returns success if it finds at least a certain number of matches (minNumToFind).
class GoalLifeStageAnywhere(lifeFormType:String = "", lifeStageName:String = "", minNumToFind:Int = 1, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // If agent is not in a container, do not continue evaluation
    if (agent.getContainer().isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Get agent location
    val agentLocation = agent.getContainer().get
    val visibleObjects = agentLocation.getContainedObjectsAndPortalsRecursive(includeHidden = false, includePortalConnections = false)

    var numFound:Int = 0
    breakable {
      for (vObj <- visibleObjects) {
        vObj match {
          case x:LivingThing => {
            if ((x.propLife.isDefined) && (x.propLife.get.lifeformType == lifeFormType)) {
              if (x.lifecycle.isDefined) {
                val curLifeStage = x.lifecycle.get.getCurStageName()
                if (curLifeStage.toLowerCase == lifeStageName.toLowerCase) {
                  // If we reach here, we've found an instance of the particular life form at the particular life stage
                  numFound += 1
                }
              }
            }
          }
          case _ => {
            // Do nothing
          }
        }
      }
    }

    // If we've found at least the number that we need to find, then success
    if (numFound >= minNumToFind) {
      return GoalReturn.mkSubgoalSuccess()
    }

    // Otherwise
    return GoalReturn.mkSubgoalUnsuccessful()

  }

}
