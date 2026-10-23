package scienceworld.actions

import language.model.{ActionExpr, ActionExprIdentifier, ActionExprOR, ActionExprObject, ActionExprText, ActionRequestDef, ActionTrigger}
import scienceworld.input.ActionDefinitions.mkActionRequest
import scienceworld.input.{ActionDefinitions, ActionHandler}
import scienceworld.objects.agent.Agent
import scienceworld.struct.EnvObject

import scala.collection.mutable.ArrayBuffer

/*
 * Action: Eat
 */
class ActionEat(action:ActionRequestDef, assignments:Map[String, EnvObject]) extends Action(action, assignments) {

  override def runAction(): (String, Boolean) = {
    val agent = assignments("agent")
    val food = assignments("food")

    // Do checks for valid action
    val (invalidStr, isValid) = ActionEat.isValidAction(assignments)
    if (!isValid) return (invalidStr, false)

    // Case 2: Poisonous?
    if (food.propEdibility.get.isPoisonous) {
      food.removeAndResetContainer()
      return ("You don't feel well.", true)
      //TODO: Health?
    }

    // Case 3: Food is edible
    food.removeAndResetContainer()
    return ("The " + food.name + " was delicious.", true)
    // TODO: Increase health/nutrients/etc

  }

}

object ActionEat {
  val ACTION_NAME = "eat"
  val ACTION_ID   = ActionDefinitions.ACTION_ID_EAT
  val isOracleAction = false

  def registerAction(actionHandler:ActionHandler) {
    val triggerPhrase = new ActionTrigger(List(
      new ActionExprOR(List("eat", "consume")),
      new ActionExprIdentifier("food")
    ))

    val action = mkActionRequest(ACTION_NAME, triggerPhrase, ACTION_ID, isOracleAction = isOracleAction)
    actionHandler.addAction(action)
  }


  def isValidAction(assignments:Map[String, EnvObject]): (String, Boolean) = {
    val agent = assignments("agent")
    val food = assignments("food")

    // Check 1: Check that agent is valid
    agent match {
      case a:Agent => { }
      case _ => return ("I'm not sure what that means", false)
    }

    // Case 2: Food is not edible
    if ((food.propEdibility.isEmpty) || (food.propEdibility.get.isEdible == false)) {
      return ("The " + food.name + " is not edible.", false)
    }

    // Unimplemented
    return ("", true)
  }

  def generatePossibleValidActions(agent:EnvObject, visibleObjects:Array[EnvObject], uuid2referentLUT:Map[Long, String]):Array[PossibleAction] = {
    val out = new ArrayBuffer[PossibleAction]()

    for (obj <- visibleObjects) {
      // Pack for check
      val assignments = Map(
        "agent" -> agent,
        "food" -> obj
      )

      // Do check
      if (this.isValidAction(assignments)._2 == true) {
        // Pack and store
        val pa = new PossibleAction(Array[ActionExpr](
          new ActionExprText("eat"),
          new ActionExprObject(obj, referent = uuid2referentLUT(obj.uuid))
        ), this.ACTION_ID)
        out.append(pa)
      }
    }

    return out.toArray
  }

}
