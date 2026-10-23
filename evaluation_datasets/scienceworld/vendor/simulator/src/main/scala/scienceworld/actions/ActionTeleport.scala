package main.scala.scienceworld.actions

import language.model.{ActionExpr, ActionExprIdentifier, ActionExprOR, ActionExprObject, ActionExprText, ActionRequestDef, ActionTrigger}
import scienceworld.actions.{Action, PossibleAction}
import scienceworld.input.ActionDefinitions.mkActionRequest
import scienceworld.input.{ActionDefinitions, ActionHandler}
import scienceworld.objects.agent.Agent
import scienceworld.objects.location.{Location, Universe}
import scienceworld.objects.portal.Door
import scienceworld.struct.EnvObject

import scala.collection.mutable.ArrayBuffer
import scala.util.control.Breaks.{break, breakable}


/*
 * Action: Teleport to location
 */
// Note: ORACLE action (can see all objects in the universe)
class ActionTeleport(action:ActionRequestDef, assignments:Map[String, EnvObject]) extends Action(action, assignments) {

  override def runAction(): (String, Boolean) = {
    val agent = assignments("agent")
    val doorOrLocation = assignments("location")

    // Do checks for valid action
    val (invalidStr, isValid) = ActionTeleport.isValidAction(assignments)
    if (!isValid) return (invalidStr, false)

    doorOrLocation match {
      case location:Location => {
        // Try to find a portal that goes from the current location to the requested location
        location.addObject(agent)
        return ("You teleport to the " + location.name + ".", true)
      }
      case _ => {
        return (Action.MESSAGE_UNKNOWN_CATCH, false)
      }
    }
    return (Action.MESSAGE_UNKNOWN_CATCH, false)
  }

}

object ActionTeleport {
  val ACTION_NAME = "teleport to location"
  val ACTION_ID   = ActionDefinitions.ACTION_ID_MOVETHRUDOOR
  val isOracleAction = true

  def registerAction(actionHandler:ActionHandler) {
    // Action: Move through door
    val triggerPhrase = new ActionTrigger(List(
      new ActionExprOR(List("teleport", "teleport to", "teleport into")),
      new ActionExprIdentifier("location")
    ))
    val action = mkActionRequest(ACTION_NAME, triggerPhrase, ACTION_ID, isOracleAction = isOracleAction)
    actionHandler.addAction(action)
  }

  def isValidAction(assignments:Map[String, EnvObject]): (String, Boolean) = {
    val agent = assignments("agent")
    val location = assignments("location")

    // Check 1: Check that agent is valid
    agent match {
      case a:Agent => { }
      case _ => return ("I'm not sure what that means", false)
    }

    // Step 2: Check that it's a valid thing to move through
    location match {
      case location:Location => {
          if (location.name.toLowerCase != "universe") {
            return ("", true)
          }
      }
      case _ => {
        return ("Its not clear how to go to " + location.name + ".", false)
      }
    }

    // Catch-all
    return ("Its not clear how to go to " + location.name + ".", false)
  }

  def generatePossibleValidActions(agent:EnvObject, visibleObjects:Array[EnvObject], uuid2referentLUT:Map[Long, String]):Array[PossibleAction] = {
    val out = new ArrayBuffer[PossibleAction]()

    for (obj <- visibleObjects) {
      // Pack for check
      val assignments = Map(
        "agent" -> agent,
        "location" -> obj
      )

      // Do check
      if (this.isValidAction(assignments)._2 == true) {
        // Pack and store
        val pa = new PossibleAction(Array[ActionExpr](
          new ActionExprText("teleport to"),
          new ActionExprObject(obj, referent = uuid2referentLUT(obj.uuid))      // TODO: Should only be valid locations
        ), this.ACTION_ID)
        out.append(pa)
      }
    }

    return out.toArray
  }

}
