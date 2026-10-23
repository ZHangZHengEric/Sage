package scienceworld.actions

import language.model.{ActionExpr, ActionExprIdentifier, ActionExprOR, ActionExprObject, ActionExprText, ActionRequestDef, ActionTrigger}
import scienceworld.input.ActionDefinitions.mkActionRequest
import scienceworld.input.{ActionDefinitions, ActionHandler}
import scienceworld.objects.agent.Agent
import scienceworld.objects.document.Document
import scienceworld.struct.EnvObject

import scala.collection.mutable.ArrayBuffer

/*
 * Action: Read
 */
class ActionRead(action:ActionRequestDef, assignments:Map[String, EnvObject]) extends Action(action, assignments) {

  override def runAction(): (String, Boolean) = {
    val agent = assignments("agent")
    val document = assignments("document")

    // Do checks for valid action
    val (invalidStr, isValid) = ActionRead.isValidAction(assignments)
    if (!isValid) return (invalidStr, false)

    document match {
      case x:Document => return (x.readDocument(), true)
      case _ => return (Action.MESSAGE_UNKNOWN_CATCH, false)
    }

  }

}

object ActionRead {
  val ACTION_NAME = "read"
  val ACTION_ID   = ActionDefinitions.ACTION_ID_READ
  val isOracleAction = false

  def registerAction(actionHandler:ActionHandler) {
    val triggerPhrase = new ActionTrigger(List(
      new ActionExprOR(List("read")),
      new ActionExprIdentifier("document")
    ))

    val action = mkActionRequest(ACTION_NAME, triggerPhrase, ACTION_ID, isOracleAction = isOracleAction)
    actionHandler.addAction(action)
  }

  def isValidAction(assignments:Map[String, EnvObject]): (String, Boolean) = {
    val agent = assignments("agent")
    val document = assignments("document")

    // Check 1: Check that agent is valid
    agent match {
      case a:Agent => { }
      case _ => return ("I'm not sure what that means", false)
    }

    // Check 2: Check that we're trying to read a valid document (that's readable)
    document match {
      case x:Document => { }
      case _ => return ("It's not clear how to read that.", false)
    }

    // Checks complete -- if we reach here, the action is valid
    return ("", true)
  }

  def generatePossibleValidActions(agent:EnvObject, visibleObjects:Array[EnvObject], uuid2referentLUT:Map[Long, String]):Array[PossibleAction] = {
    val out = new ArrayBuffer[PossibleAction]()

    for (obj <- visibleObjects) {
      // Pack for check
      val assignments = Map(
        "agent" -> agent,
        "document" -> obj
      )

      // Do check
      if (this.isValidAction(assignments)._2 == true) {
        // Pack and store
        val pa = new PossibleAction(Array[ActionExpr](
          new ActionExprText("read"),
          new ActionExprObject(obj, referent = uuid2referentLUT(obj.uuid))
        ), this.ACTION_ID)
        out.append(pa)
      }
    }

    return out.toArray
  }
}
