package scienceworld.actions

import language.model.{ActionExpr, ActionExprIdentifier, ActionExprOR, ActionExprText, ActionRequestDef, ActionTrigger}
import scienceworld.input.ActionDefinitions.mkActionRequest
import scienceworld.input.{ActionDefinitions, ActionHandler}
import scienceworld.objects.agent.Agent
import scienceworld.objects.document.Document
import scienceworld.struct.EnvObject

/*
 * Action: Wait
 */
class ActionWait10(action:ActionRequestDef, assignments:Map[String, EnvObject]) extends Action(action, assignments) {

  override def runAction(): (String, Boolean) = {
    val agent = assignments("agent")
    val waitTime:Int = 10     // Number of iterations to wait for

    // Do checks for valid action
    val (invalidStr, isValid) = ActionWait10.isValidAction(assignments)
    if (!isValid) return (invalidStr, false)

    agent match {
      case a:Agent => {
        a.setWait(waitTime)
        return ("You decide to wait for " + waitTime + " iterations.", true)
      }
    }

  }

}

object ActionWait10 {
  val ACTION_NAME = "wait10"
  val ACTION_ID   = ActionDefinitions.ACTION_ID_WAIT10
  val isOracleAction = false

  def registerAction(actionHandler:ActionHandler) {
    val triggerPhrase = new ActionTrigger(List(
      new ActionExprOR(List("wait")),
    ))

    val action = mkActionRequest(ACTION_NAME, triggerPhrase, ACTION_ID, isOracleAction = isOracleAction)
    actionHandler.addAction(action)
  }

  // This action is essentially always valid
  def isValidAction(assignments:Map[String, EnvObject]): (String, Boolean) = {
    // Check 1: Check that agent is valid
    val agent = assignments("agent")
    agent match {
      case a:Agent => { }
      case _ => return ("I'm not sure what that means", false)
    }

    // Checks complete -- if we reach here, the action is valid
    return ("", true)
  }

  def generatePossibleValidActions(agent:EnvObject, visibleObjects:Array[EnvObject], uuid2referentLUT:Map[Long, String]):Array[PossibleAction] = {
    // Single possible valid action
    val pa = new PossibleAction(Array[ActionExpr](
       new ActionExprText("wait")
    ), this.ACTION_ID)
    return Array( pa )
  }

}

class ActionWait1(action:ActionRequestDef, assignments:Map[String, EnvObject]) extends Action(action, assignments) {

  override def runAction(): (String, Boolean) = {
    val agent = assignments("agent")
    val waitTime:Int = 1     // Number of iterations to wait for

    // Do checks for valid action
    val (invalidStr, isValid) = ActionWait1.isValidAction(assignments)
    if (!isValid) return (invalidStr, false)

    agent match {
      case a:Agent => {
        a.setWait(waitTime)
        return ("You decide to wait for " + waitTime + " iterations.", true)
      }
    }

  }

}

object ActionWait1 {
  val ACTION_NAME = "wait1"
  val ACTION_ID   = ActionDefinitions.ACTION_ID_WAIT1
  val isOracleAction = false

  def registerAction(actionHandler:ActionHandler) {
    val triggerPhrase = new ActionTrigger(List(
      new ActionExprOR(List("wait1")),
    ))

    val action = mkActionRequest(ACTION_NAME, triggerPhrase, ACTION_ID, isOracleAction = isOracleAction)
    actionHandler.addAction(action)
  }

  // This action is essentially always valid
  def isValidAction(assignments:Map[String, EnvObject]): (String, Boolean) = {
    // Check 1: Check that agent is valid
    val agent = assignments("agent")
    agent match {
      case a:Agent => { }
      case _ => return ("I'm not sure what that means", false)
    }

    // Checks complete -- if we reach here, the action is valid
    return ("", true)
  }

  def generatePossibleValidActions(agent:EnvObject, visibleObjects:Array[EnvObject], uuid2referentLUT:Map[Long, String]):Array[PossibleAction] = {
    // Single possible valid action
    val pa = new PossibleAction(Array[ActionExpr](
      new ActionExprText("wait1")
    ), this.ACTION_ID)
    return Array( pa )
  }

}
