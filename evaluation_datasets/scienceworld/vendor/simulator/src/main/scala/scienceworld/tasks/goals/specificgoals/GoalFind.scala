package scienceworld.tasks.goals.specificgoals

import scienceworld.objects.agent.Agent
import scienceworld.objects.livingthing.LivingThing
import scienceworld.objects.misc.InclinedPlane
import scienceworld.objects.taskitems.AnswerBox
import scienceworld.struct.EnvObject
import scienceworld.tasks.goals.{Goal, GoalReturn, GoalSequence}

// Find an object with a specific name
class GoalFind(objectName:String = "", failIfWrong:Boolean = true, _defocusOnSuccess:Boolean = false, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.defocusOnSuccess = _defocusOnSuccess
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    if (obj.get.name.toLowerCase == objectName.toLowerCase) {
      // Case: The focus is on an object with the correct name
      this.satisfiedWithObject = obj
      return GoalReturn.mkSubgoalSuccess()
    } else {
      // Case: The focus is on an object with a different name
      if (failIfWrong) {
        // Return: Task failure
        return GoalReturn.mkTaskFailure()
      } else {
        // Return: Subgoal not passed
        return GoalReturn.mkSubgoalUnsuccessful()
      }
    }

  }

}

class GoalFindAnswerBox(objectName:String = "", failIfWrong:Boolean = true, _defocusOnSuccess:Boolean = false, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.defocusOnSuccess = _defocusOnSuccess
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Do not fail if the focus is on something other than an answer box
    if (!obj.get.isInstanceOf[AnswerBox]) return GoalReturn.mkSubgoalUnsuccessful()

    if (obj.get.name.toLowerCase == objectName.toLowerCase) {
      // Case: The focus is on an object with the correct name
      this.satisfiedWithObject = obj
      return GoalReturn.mkSubgoalSuccess()
    } else {
      // Case: The focus is on an object with a different name
      if (failIfWrong) {
        // Return: Task failure
        return GoalReturn.mkTaskFailure()
      } else {
        // Return: Subgoal not passed
        return GoalReturn.mkSubgoalUnsuccessful()
      }
    }

  }

}


class GoalFindLivingThingStage(livingThingType:String = "", lifeStage:String = "", failIfWrong:Boolean = true, _defocusOnSuccess:Boolean = false, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.defocusOnSuccess = _defocusOnSuccess
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    println("GoalFindLivingThingStage()")
    if (obj.get.propLife.isDefined) {
      println(" -> " + obj.get.propLife.get.lifeformType)
    }
    println(" --> " + livingThingType)
    // Case: The focus is on a living thing of the correct species type
    if ((obj.get.propLife.isDefined) && (obj.get.propLife.get.lifeformType == livingThingType.toLowerCase)) {

      // Step 2: Check that it's in the correct life cycle stage
      obj.get match {
        case x:LivingThing => {
          // Check that the object has a Life Cycle defined
          if (x.lifecycle.isDefined) {
            // Check that the life cycle stage is the one we're looking for
            println("### (" + x.lifecycle.get.getCurStageName() + " / " + lifeStage + ")")
            if (x.lifecycle.get.getCurStageName() == lifeStage) {
              this.satisfiedWithObject = obj
              return GoalReturn.mkSubgoalSuccess()
            }
          }
        }
        case _ => {
          // Do nothing
        }
      }

    }
    // Case: The focus is on an object with a different name
    if (failIfWrong) {
      // Return: Task failure
      return GoalReturn.mkTaskFailure()
    } else {
      // Return: Subgoal not passed
      return GoalReturn.mkSubgoalUnsuccessful()
    }


  }

}


class GoalFindInclinedPlane(surfaceName:String = "", failIfWrong:Boolean = true, _defocusOnSuccess:Boolean = false, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.defocusOnSuccess = _defocusOnSuccess
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    if (obj.get.name.toLowerCase == "inclined plane") {
      obj.get match {
        case x:InclinedPlane => {
          if (x.surfaceMaterial.substanceName == surfaceName) {
            // Case: The focus is on an object with the correct name
            this.satisfiedWithObject = obj
            return GoalReturn.mkSubgoalSuccess()
          }
        }
        case _ => { }
      }
    }

    // Case: The focus is on an object with a different name
    if (failIfWrong) {
      // Return: Task failure
      return GoalReturn.mkTaskFailure()
    } else {
      // Return: Subgoal not passed
      return GoalReturn.mkSubgoalUnsuccessful()
    }

  }

}

class GoalFindInclinedPlaneNamed(additionalName:String = "", failIfWrong:Boolean = true, _defocusOnSuccess:Boolean = false, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.defocusOnSuccess = _defocusOnSuccess
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    if (obj.get.name.toLowerCase == "inclined plane") {
      obj.get match {
        case x:InclinedPlane => {
          if (x.additionalName == additionalName) {
            // Case: The focus is on an object with the correct name
            this.satisfiedWithObject = obj
            return GoalReturn.mkSubgoalSuccess()
          }
        }
        case _ => { }
      }
    }

    // Case: The focus is on an object with a different name
    if (failIfWrong) {
      // Return: Task failure
      return GoalReturn.mkTaskFailure()
    } else {
      // Return: Subgoal not passed
      return GoalReturn.mkSubgoalUnsuccessful()
    }

  }

}
