package scienceworld.actions

import language.model.{ActionExpr, ActionExprIdentifier, ActionExprOR, ActionExprObject, ActionExprText, ActionRequestDef, ActionTrigger}
import scienceworld.objects.portal.Door
import scienceworld.input.ActionDefinitions.mkActionRequest
import scienceworld.input.{ActionDefinitions, ActionHandler}
import scienceworld.objects.agent.Agent
import scienceworld.objects.location.Location
import scienceworld.struct.EnvObject

import scala.collection.mutable.ArrayBuffer
import scala.util.control.Breaks._


/*
 * Action: Move through door
 */
class ActionMoveThroughDoor(action:ActionRequestDef, assignments:Map[String, EnvObject]) extends Action(action, assignments) {

  override def runAction(): (String, Boolean) = {
    val agent = assignments("agent")
    val doorOrLocation = assignments("doorOrLocation")

    // Do checks for valid action
    val (invalidStr, isValid) = ActionMoveThroughDoor.isValidAction(assignments)
    if (!isValid) return (invalidStr, false)

    doorOrLocation match {
      // Case 1: Moving through door
      case door:Door => {
        // Move the agent through door

        // First, check which side of the door we're on
        val door1 = door.asInstanceOf[Door]
        val agentContainer = agent.getContainer().get
        var connectsTo = door1.getConnectsTo(agentContainer)

        // Then, move the agent to the other side
        connectsTo.get.addObject(agent)
        return ("You move through the " + door.name + " to the " + connectsTo.get.name + ".", true)

      }
      case location:Location => {
        // Try to find a portal that goes from the current location to the requested location
        val agentLocation = agent.getContainerRecursiveOfType[Location]()
        for (portal <- agentLocation.get.getPortals()) {
          breakable {
            // Find a list of the referent names that this portal connects to
            val connectsTo = portal.getConnectsTo(perspectiveContainer = agentLocation.get)
            if (connectsTo.isEmpty) break
            val connectsToLocationReferents = connectsTo.get.getReferents()
            // If one of the referents is the same as the location we're looking for, then try to go through that portal
            if (connectsToLocationReferents.contains(location.name)) {
              // If we reach here, move the agent through the portal
              location.addObject(agent)
              return ("You move to the " + location.name + ".", true)
            }
          }
        }

      }
      case _ => {
        return (Action.MESSAGE_UNKNOWN_CATCH, false)
      }
    }
    return (Action.MESSAGE_UNKNOWN_CATCH, false)
  }

}

object ActionMoveThroughDoor {
  val ACTION_NAME = "move through door"
  val ACTION_ID   = ActionDefinitions.ACTION_ID_MOVETHRUDOOR
  val isOracleAction = false

  def registerAction(actionHandler:ActionHandler) {
    // Action: Move through door
    val triggerPhrase = new ActionTrigger(List(
      new ActionExprOR(List("go", "go through", "walk through", "move through", "go to", "walk to", "move to", "go into", "move into")),
      new ActionExprIdentifier("doorOrLocation")
    ))
    val action = mkActionRequest(ACTION_NAME, triggerPhrase, ACTION_ID, isOracleAction = isOracleAction)
    actionHandler.addAction(action)
  }

  def isValidAction(assignments:Map[String, EnvObject]): (String, Boolean) = {
    val agent = assignments("agent")
    val doorOrLocation = assignments("doorOrLocation")

    // Check 1: Check that agent is valid
    agent match {
      case a:Agent => { }
      case _ => return ("I'm not sure what that means", false)
    }

    // Step 2: Check that it's a valid thing to move through
    doorOrLocation match {
      // Case 1: Moving through door
      case door:Door => {
        // Check to make sure the door is passable
        if (!door.isCurrentlyPassable()) {
          // Return a human-readable message for why the door isn't passable
          return (door.getUnpassableErrorMessage(), false)
        }

        // Make sure the door goes somewhere valid
        // First, check which side of the door we're on
        val door1 = door.asInstanceOf[Door]
        val agentContainer = agent.getContainer().get
        var connectsTo = door1.getConnectsTo(agentContainer)
        if (connectsTo.isEmpty) {
          return ("The door doesn't appear to go anywhere.", false)
        }

        // If we reach here, the action is valid
        return ("", true)

      }
      case location:Location => {
        // Try to find a portal that goes from the current location to the requested location
        val agentLocation = agent.getContainerRecursiveOfType[Location]()
        if (agentLocation.isEmpty) return ("<ERROR> The agent doesn't appear to be in a valid location.", false)

        for (portal <- agentLocation.get.getPortals()) {
          breakable {
            // Find a list of the referent names that this portal connects to
            val connectsTo = portal.getConnectsTo(perspectiveContainer = agentLocation.get)
            if (connectsTo.isEmpty) break
            val connectsToLocationReferents = connectsTo.get.getReferents()
            // If one of the referents is the same as the location we're looking for, then try to go through that portal
            if (connectsToLocationReferents.contains(location.name)) {
              if (!portal.isCurrentlyPassable()) {
                // Return a human-readable message for why the door isn't passable
                return (portal.getUnpassableErrorMessage(), false)
              }
              // If we reach here, the action is valid
              return ("", true)
            }
          }
        }

        return ("It's not clear how to get there from here.", false)
      }
      case _ => {
        return ("Its not clear how to go to/through a " + doorOrLocation.name + ".", false)
      }
    }

    // Catch-all
    return ("Its not clear how to go to/through a " + doorOrLocation.name + ".", false)
  }

  def generatePossibleValidActions(agent:EnvObject, visibleObjects:Array[EnvObject], uuid2referentLUT:Map[Long, String]):Array[PossibleAction] = {
    val out = new ArrayBuffer[PossibleAction]()

    for (obj <- visibleObjects) {
      // Pack for check
      val assignments = Map(
        "agent" -> agent,
        "doorOrLocation" -> obj
      )

      // Do check
      if (this.isValidAction(assignments)._2 == true) {
        // Pack and store
        val pa = new PossibleAction(Array[ActionExpr](
          new ActionExprText("go to"),
          new ActionExprObject(obj, referent = uuid2referentLUT(obj.uuid))
        ), this.ACTION_ID)
        out.append(pa)
      }
    }

    return out.toArray
  }

}
