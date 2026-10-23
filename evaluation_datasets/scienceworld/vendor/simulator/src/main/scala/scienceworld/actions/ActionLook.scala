package scienceworld.actions

import language.model.{ActionExpr, ActionExprIdentifier, ActionExprOR, ActionExprObject, ActionExprText, ActionRequestDef, ActionTrigger}
import scienceworld.input.ActionDefinitions.mkActionRequest
import scienceworld.input.{ActionDefinitions, ActionHandler}
import scienceworld.objects.agent.Agent
import scienceworld.objects.portal.Portal
import scienceworld.struct.EnvObject
import scienceworld.struct.EnvObject._
import util.StringHelpers

import scala.collection.mutable.ArrayBuffer


/*
 * Action: Look Around
 */
class ActionLookAround(action:ActionRequestDef, assignments:Map[String, EnvObject]) extends Action(action, assignments) {

  override def runAction(): (String, Boolean) = {
    val agent = assignments("agent")

    // Do checks for valid action
    val (invalidStr, isValid) = ActionLookAround.isValidAction(assignments)
    if (!isValid) return (invalidStr, false)

    val container = agent.getContainer().get
    val containerDescription = container.getDescriptionSafe(mode = MODE_DETAILED).getOrElse("<ERROR: attempting to view hidden object>")    //## TODO: Arguable whether the error case here should be caught by checks above
    return (containerDescription, true)

  }

}

object ActionLookAround {
  val ACTION_NAME = "look around"
  val ACTION_ID   = ActionDefinitions.ACTION_ID_LOOK_AROUND
  val isOracleAction = false

  def registerAction(actionHandler:ActionHandler) {
    val triggerPhrase = new ActionTrigger(List(
      new ActionExprOR(List("look around", "look"))
    ))

    val action = mkActionRequest(ACTION_NAME, triggerPhrase, ACTION_ID, isOracleAction = isOracleAction)
    actionHandler.addAction(action)
  }

  // This action is essentially always valid
  def isValidAction(assignments:Map[String, EnvObject]): (String, Boolean) = {
    // Check 1: Check that agent is valid
    val agent = assignments("agent")
    agent match {
      case a:Agent => {
        if (a.getContainer().isEmpty) return ("<ERROR> The agent is not in a container (this should never happen)", false)
      }
      case _ => return ("<ERROR> Invalid agent.", false)
    }

    // Checks complete -- if we reach here, the action is valid
    return ("", true)
  }

  def generatePossibleValidActions(agent:EnvObject, visibleObjects:Array[EnvObject], uuid2referentLUT:Map[Long, String]):Array[PossibleAction] = {
    // Single possible valid action
    val pa = new PossibleAction(Array[ActionExpr](
      new ActionExprText("look around")
    ), this.ACTION_ID)
    return Array( pa )
  }
}



/*
 * Action: Look at object
 */
class ActionLookAt(action:ActionRequestDef, assignments:Map[String, EnvObject]) extends Action(action, assignments) {

  override def runAction(): (String, Boolean) = {
    val agent = assignments("agent")
    val obj = assignments("obj")

    // Do checks for valid action
    val (invalidStr, isValid) = ActionLookAt.isValidAction(assignments)
    if (!isValid) return (invalidStr, false)

    // Modified version, with special handling for Portal objects
    val mode = MODE_DETAILED
    var objDescription = "<ERROR: Could not retrieve object description>"   // This error should never happen
    // Get the perspective container
    if (agent.getContainer().isDefined) {       // This should always be the case unless something terrible has happened
      val perspectiveContainer = agent.getContainer().get
      obj match {
        case x: Portal => {
          val desc = x.getDescriptionSafe(mode, perspectiveContainer)
          if (desc.isDefined) objDescription = desc.get
        }
        case x: EnvObject => {
          val desc = x.getDescriptionSafe(mode)
          if (desc.isDefined) objDescription = desc.get
        }
      }
    }
    return (objDescription, true)

  }

}

object ActionLookAt {
  val ACTION_NAME = "look at"
  val ACTION_ID   = ActionDefinitions.ACTION_ID_LOOK_AT
  val isOracleAction = false

  def registerAction(actionHandler:ActionHandler) {
    val triggerPhrase = new ActionTrigger(List(
      new ActionExprOR(List("look at", "look on", "examine")),
      new ActionExprIdentifier("obj")
    ))

    val action = mkActionRequest(ACTION_NAME, triggerPhrase, ACTION_ID, isOracleAction = isOracleAction)
    actionHandler.addAction(action)
  }

  // This action is essentially always valid
  def isValidAction(assignments:Map[String, EnvObject]): (String, Boolean) = {
    // Check 1: Check that agent is valid
    val agent = assignments("agent")
    agent match {
      case a:Agent => {
        if (a.getContainer().isEmpty) return ("<ERROR> The agent is not in a container (this should never happen)", false)
      }
      case _ => return ("<ERROR> Invalid agent.", false)
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
        /*
        println ("obj: " + obj.toStringMinimal())
        if (obj.getContainer().isDefined) {
          println("\t container: " + obj.getContainer().get.toStringMinimal())
        }
         */

        // Pack and store
        val pa = new PossibleAction(Array[ActionExpr](
          new ActionExprText("look at"),
          new ActionExprObject(obj, referent = uuid2referentLUT(obj.uuid))
        ), this.ACTION_ID)
        out.append(pa)
      }
    }

    return out.toArray
  }

}


/*
 * Action: Look in object
 */
class ActionLookIn(action:ActionRequestDef, assignments:Map[String, EnvObject]) extends Action(action, assignments) {

  override def runAction(): (String, Boolean) = {
    val agent = assignments("agent")
    val obj = assignments("obj")
    val os = new StringBuilder()

    // Do checks for valid action
    val (invalidStr, isValid) = ActionLookIn.isValidAction(assignments)
    if (!isValid) return (invalidStr, false)

    // Run action
    if (obj.propContainer.isDefined) {
      if (obj.propContainer.get.isOpen) {
        // Normal case -- look inside the container
        val containedObjs = obj.getContainedObjects()
        if (containedObjs.size == 0) {
          os.append ("There is nothing in the " + obj.name + ".")
        } else {
          val objNames = containedObjs.map(_.name)
          os.append ("Inside the " + obj.name + " is: \n")
          os.append( StringHelpers.objectListToStringDescription(obj.getContainedObjects(), perspectiveContainer=agent, multiline = true)  )
        }
        os.append("\n")
      }

      if (obj.getPortals().size > 0) {
        os.append(" You also see: ")
        val descriptions = new ArrayBuffer[String]
        for (portal <- obj.getPortals()) {
          val desc = portal.getDescriptionSafe(mode = MODE_CURSORY_DETAIL, perspectiveContainer = obj)
          if (desc.isDefined) descriptions.append(desc.get)
        }
        os.append(descriptions.mkString(", "))
        os.append(".")
      }
    }

    // Return
    return (os.toString, true)
  }

}

object ActionLookIn {
  val ACTION_NAME = "look in"
  val ACTION_ID   = ActionDefinitions.ACTION_ID_LOOK_IN
  val isOracleAction = false

  def registerAction(actionHandler:ActionHandler) {
    val triggerPhrase = new ActionTrigger(List(
      new ActionExprOR(List("look in")),
      new ActionExprIdentifier("obj")
    ))

    val action = mkActionRequest(ACTION_NAME, triggerPhrase, ACTION_ID, isOracleAction = isOracleAction)
    actionHandler.addAction(action)
  }

  // This action is essentially always valid
  def isValidAction(assignments:Map[String, EnvObject]): (String, Boolean) = {
    // Check 1: Check that agent is valid
    val agent = assignments("agent")
    val obj = assignments("obj")

    agent match {
      case a:Agent => {
        if (a.getContainer().isEmpty) return ("<ERROR> The agent is not in a container (this should never happen)", false)
      }
      case _ => return ("<ERROR> Invalid agent.", false)
    }

    // Check 2: If it's a container, check that it's open
    if (obj.propContainer.isDefined) {
      if (!obj.propContainer.get.isOpen) {
        // Unopen container -- fail
        return ("The " + obj.name + " isn't open, so you can't see inside.", false)
      }
      // Open container -- OK
      return ("", true)
    }

    // If we reach here, it's not a container, so we can't look in it
    return ("It's not clear how to look inside of that.", false)
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
          new ActionExprText("look in"),
          new ActionExprObject(obj, referent = uuid2referentLUT(obj.uuid))
        ), this.ACTION_ID)
        out.append(pa)
      }
    }

    return out.toArray
  }
}
