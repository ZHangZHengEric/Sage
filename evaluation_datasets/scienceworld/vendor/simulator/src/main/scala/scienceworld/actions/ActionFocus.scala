package scienceworld.actions

import language.model.{ActionExpr, ActionExprIdentifier, ActionExprOR, ActionExprObject, ActionExprText, ActionRequestDef, ActionTrigger}
import scienceworld.input.ActionDefinitions.mkActionRequest
import scienceworld.input.{ActionDefinitions, ActionHandler}
import scienceworld.objects.agent.Agent
import scienceworld.struct.EnvObject
import scienceworld.tasks.goals.{GoalSequence, ObjMonitor}

import scala.collection.mutable.ArrayBuffer

/*
 * Action: Focus
 */
class ActionFocus(action:ActionRequestDef, assignments:Map[String, EnvObject], objMonitor:ObjMonitor) extends Action(action, assignments) {

  override def runAction(): (String, Boolean) = {
    val agent = assignments("agent")
    val obj = assignments("obj")

    // Do checks for valid action
    val (invalidStr, isValid) = ActionFocus.isValidAction(assignments)
    if (!isValid) return (invalidStr, false)

    // Do action
    objMonitor.clearMonitoredObjects()
    objMonitor.addMonitor(obj)

    return ("You focus on the " + obj.getDescriptName() + ".", true)
  }

}

object ActionFocus {
  val ACTION_NAME = "focus on"
  val ACTION_ID   = ActionDefinitions.ACTION_ID_FOCUS
  val isOracleAction = false

  def registerAction(actionHandler:ActionHandler) {
    val triggerPhrase = new ActionTrigger(List(
      new ActionExprOR(List("focus on", "focus")),
      new ActionExprIdentifier("obj")
    ))

    val action = mkActionRequest(ACTION_NAME, triggerPhrase, ACTION_ID, isOracleAction = isOracleAction)
    actionHandler.addAction(action)
  }


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
    val out = new ArrayBuffer[PossibleAction]()

    for (obj <- visibleObjects) {
      // Pack for check
      val assignments = Map(
        "agent" -> agent,
        "obj" -> obj
      )

      // Do check
      if (this.isValidAction(assignments)._2 == true) {
        // Pack and store
        val pa = new PossibleAction(Array[ActionExpr](
          new ActionExprText("focus on"),
          new ActionExprObject(obj, referent = uuid2referentLUT(obj.uuid))
        ), this.ACTION_ID)
        out.append(pa)
      }
    }

    return out.toArray
  }
}

/*
 * Action: Focus
 */
class ActionResetTask(action:ActionRequestDef, assignments:Map[String, EnvObject], objMonitor:ObjMonitor, goalSequence:GoalSequence) extends Action(action, assignments) {

  override def runAction(): (String, Boolean) = {
    val agent = assignments("agent")

    // Do checks for valid action
    val (invalidStr, isValid) = ActionResetTask.isValidAction(assignments)
    if (!isValid) return (invalidStr, false)

    goalSequence.reset()
    objMonitor.clearMonitoredObjects()

    return ("You reset the goal progress and focus.", true)
  }

}

object ActionResetTask {
  val ACTION_NAME = "reset task"
  val ACTION_ID   = ActionDefinitions.ACTION_ID_RESETTASK
  val isOracleAction = false

  def registerAction(actionHandler:ActionHandler) {
    val triggerPhrase = new ActionTrigger(List(
      new ActionExprOR(List("reset task")),
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
      new ActionExprText("reset task")
    ), this.ACTION_ID)
    return Array( pa )
  }

}
