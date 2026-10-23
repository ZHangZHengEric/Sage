package scienceworld.actions

import language.model.{ActionExpr, ActionExprIdentifier, ActionExprOR, ActionExprObject, ActionExprText, ActionRequestDef, ActionTrigger}
import scienceworld.objects.portal.Door
import scienceworld.input.ActionDefinitions.mkActionRequest
import scienceworld.input.{ActionDefinitions, ActionHandler}
import scienceworld.objects.agent.Agent
import scienceworld.struct.EnvObject

import scala.collection.mutable.ArrayBuffer

/*
 * Action: Open Door
 */
class ActionOpenDoor(action:ActionRequestDef, assignments:Map[String, EnvObject]) extends Action(action, assignments) {

  override def runAction(): (String, Boolean) = {
    val agent = assignments("agent")
    val obj = assignments("door")

    // Do checks for valid action
    val (invalidStr, isValid) = ActionOpenDoor.isValidAction(assignments)
    if (!isValid) return (invalidStr, false)


    // Case 1: Openable portals (e.g. doors)
    if (obj.propPortal.isDefined) {
      // Open
      if (!obj.propPortal.get.isOpen) {
        if (obj.propPortal.get.isOpenable) {
          obj.propPortal.get.isOpen = true
          return ("The " + obj.name + " is now open.", true)
        }
      }
    }

    // Case 2: Openable containers (e.g. cupboards)
    if (obj.propContainer.isDefined) {
      // Open
      if (!obj.propContainer.get.isOpen) {
        obj.propContainer.get.isOpen = true
        return ("The " + obj.name + " is now open.", true)
      }
    }

    return (Action.MESSAGE_UNKNOWN_CATCH, false)
  }

}

object ActionOpenDoor {
  val ACTION_NAME = "open door"
  val ACTION_ID   = ActionDefinitions.ACTION_ID_OPEN
  val isOracleAction = false

  def registerAction(actionHandler:ActionHandler) {
    val triggerPhrase = new ActionTrigger(List(
      new ActionExprOR(List("open")),
      new ActionExprIdentifier("door")
    ))
    val action = mkActionRequest(ACTION_NAME, triggerPhrase, ACTION_ID, isOracleAction = isOracleAction)
    actionHandler.addAction(action)
  }

  def isValidAction(assignments:Map[String, EnvObject]): (String, Boolean) = {
    val agent = assignments("agent")
    val obj = assignments("door")

    // Check 1: Check that agent is valid
    agent match {
      case a:Agent => { }
      case _ => return ("I'm not sure what that means", false)
    }

    // Case 2: Openable portals (e.g. doors)
    if (obj.propPortal.isDefined) {
      // Open
      if (obj.propPortal.get.isOpen) {
        return ("The " + obj.name + " is already open.", false)
      } else {
        if (!obj.propPortal.get.isOpenable) {
          return ("The " + obj.name + " is not openable.", false)
        }
      }
    }

    // Case 2: Openable containers (e.g. cupboards)
    if (obj.propContainer.isDefined) {
      if (!obj.propContainer.get.isClosable) {
        return ("The " + obj.name + " is not openable.", false)
      }

      // Open
      if (obj.propContainer.get.isOpen) {
        return ("The " + obj.name + " is already open.", false)
      }
    }

    // Case 3: Not a portal or a container
    if ((obj.propPortal.isEmpty) && (obj.propContainer.isEmpty)) {
      return ("The " + obj.name + " is not openable.", false)
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
        "door" -> obj
      )

      // Do check
      if (this.isValidAction(assignments)._2 == true) {
        // Pack and store
        val pa = new PossibleAction(Array[ActionExpr](
          new ActionExprText("open"),
          new ActionExprObject(obj, referent = uuid2referentLUT(obj.uuid))
        ), this.ACTION_ID)
        out.append(pa)
      }
    }

    return out.toArray
  }
}


/*
 * Action: Close Door
 */
class ActionCloseDoor(action:ActionRequestDef, assignments:Map[String, EnvObject]) extends Action(action, assignments) {

  override def runAction(): (String, Boolean) = {
    val agent = assignments("agent")
    val obj = assignments("door")

    // Do checks for valid action
    val (invalidStr, isValid) = ActionCloseDoor.isValidAction(assignments)
    if (!isValid) return (invalidStr, false)


    // Case 1: Openable portals (e.g. doors)
    if (obj.propPortal.isDefined) {
      // Open
      if (obj.propPortal.get.isOpen) {
        if (obj.propPortal.get.isOpenable) {
          obj.propPortal.get.isOpen = false
          return ("The " + obj.name + " is now closed.", true)
        }
      }
    }

    // Case 2: Openable containers (e.g. cupboards)
    if (obj.propContainer.isDefined) {
      // Open
      if (obj.propContainer.get.isOpen) {
        obj.propContainer.get.isOpen = false
        return ("The " + obj.name + " is now closed.", true)
      }
    }


    return (Action.MESSAGE_UNKNOWN_CATCH, false)
  }

}

object ActionCloseDoor {
  val ACTION_NAME = "close door"
  val ACTION_ID   = ActionDefinitions.ACTION_ID_CLOSE
  val isOracleAction = false

  def registerAction(actionHandler:ActionHandler) {
    val triggerPhrase = new ActionTrigger(List(
      new ActionExprOR(List("close")),
      new ActionExprIdentifier("door")
    ))
    val action = mkActionRequest(ACTION_NAME, triggerPhrase, ACTION_ID, isOracleAction = isOracleAction)
    actionHandler.addAction(action)
  }

  def isValidAction(assignments:Map[String, EnvObject]): (String, Boolean) = {
    val agent = assignments("agent")
    val obj = assignments("door")

    // Check 1: Check that agent is valid
    agent match {
      case a:Agent => { }
      case _ => return ("I'm not sure what that means", false)
    }

    // Case 1: Openable portals (e.g. doors)
    if (obj.propPortal.isDefined) {
      // Open
      if (!obj.propPortal.get.isOpen) {
        return ("The " + obj.name + " is already closed.", false)
      } else {
        if (!obj.propPortal.get.isOpenable) {
          return ("The " + obj.name + " is not closeable.", false)
        }
      }
    }

    // Case 2: Openable containers (e.g. cupboards)
    if (obj.propContainer.isDefined) {
      if (!obj.propContainer.get.isClosable) {
        return ("The " + obj.name + " is not closeable.", false)
      }

      // Open
      if (!obj.propContainer.get.isOpen) {
        return ("The " + obj.name + " is already closed.", false)
      }
    }

    // Case 3: Not a portal or a container
    if ((obj.propPortal.isEmpty) && (obj.propContainer.isEmpty)) {
      return ("The " + obj.name + " is not closeable.", false)
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
        "door" -> obj
      )

      // Do check
      if (this.isValidAction(assignments)._2 == true) {
        // Pack and store
        val pa = new PossibleAction(Array[ActionExpr](
          new ActionExprText("close"),
          new ActionExprObject(obj, referent = uuid2referentLUT(obj.uuid))
        ), this.ACTION_ID)
        out.append(pa)
      }
    }

    return out.toArray
  }
}
