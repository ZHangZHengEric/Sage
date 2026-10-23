package scienceworld.actions

import language.model.{ActionExpr, ActionExprIdentifier, ActionExprOR, ActionExprObject, ActionExprText, ActionRequestDef, ActionTrigger}
import scienceworld.input.ActionDefinitions.mkActionRequest
import scienceworld.input.{ActionDefinitions, ActionHandler}
import scienceworld.objects.agent.Agent
import scienceworld.objects.electricalcomponent.{PolarizedElectricalComponent, Terminal, UnpolarizedElectricalComponent}
import scienceworld.struct.EnvObject

import scala.collection.mutable.ArrayBuffer


/*
 * Action: Connect (Electrically)
 */
class ActionConnectElectrical(action:ActionRequestDef, assignments:Map[String, EnvObject]) extends Action(action, assignments) {

  override def runAction(): (String, Boolean) = {
    val agent = assignments("agent")
    var terminalA = assignments("terminalA")
    var terminalB = assignments("terminalB")

    // Do checks for valid action
    val (invalidStr, isValid) = ActionConnectElectrical.isValidAction(assignments)
    if (!isValid) return (invalidStr, false)

    // Get terminals (this is repeated in this.isValidAction()... )

    // Make sure the specified terminal is valid (terminal A)
    val (_terminalA, errStrA, successA) = ActionConnectElectrical.getTerminal(terminalA)
    if (!successA) return (errStrA, false)
    terminalA = _terminalA
    // Make sure the specified terminal is valid (terminal B)
    val (_terminalB, errStrB, successB) = ActionConnectElectrical.getTerminal(terminalB)
    if (!successB) return (errStrB, false)
    terminalB = _terminalB


    // Do connection
    terminalA.propElectricalConnection.get.addConnection(terminalB)
    terminalB.propElectricalConnection.get.addConnection(terminalA)
    val terminalAObj:String = terminalA.asInstanceOf[Terminal].parentObject.name
    val terminalBObj:String = terminalB.asInstanceOf[Terminal].parentObject.name

    return (terminalA.name + " on " + terminalAObj + " is now connected to " + terminalB.name + " on " + terminalBObj, true)
  }

}

object ActionConnectElectrical {
  val ACTION_NAME = "connect electrically"
  val ACTION_ID   = ActionDefinitions.ACTION_ID_CONNECT
  val isOracleAction = false

  def registerAction(actionHandler:ActionHandler) {
    // Action: Move
    val triggerPhrase = new ActionTrigger(List(
      new ActionExprOR(List("connect")),
      new ActionExprIdentifier("terminalA"),
      new ActionExprOR(List("to", "in", "into")),
      new ActionExprIdentifier("terminalB")
    ))
    val action = mkActionRequest(ACTION_NAME, triggerPhrase, ACTION_ID, isOracleAction = isOracleAction)
    actionHandler.addAction(action)

  }

  def isValidAction(assignments:Map[String, EnvObject]): (String, Boolean) = {
    val agent = assignments("agent")
    var terminalA = assignments("terminalA")
    var terminalB = assignments("terminalB")

    // Check 1: Check that agent is valid
    agent match {
      case a:Agent => { }
      case _ => return ("I'm not sure what that means", false)
    }

    // Check 2: Terminals
    // Make sure the specified terminal is valid (terminal A)
    val (_terminalA, errStrA, successA) = this.getTerminal(terminalA)
    if (!successA) return (errStrA, false)
    terminalA = _terminalA
    // Make sure the specified terminal is valid (terminal B)
    val (_terminalB, errStrB, successB) = this.getTerminal(terminalB)
    if (!successB) return (errStrB, false)
    terminalB = _terminalB

    if (terminalA.uuid == terminalB.uuid) {
      return ("Something can't be connected to itself.", false)
    }

    // Check 3: Check that the objects are connectable
    if (terminalA.propElectricalConnection.isEmpty) return ("It's not clear how to connect something to " + terminalA.name, false)
    if (terminalB.propElectricalConnection.isEmpty) return ("It's not clear how to connect something to " + terminalB.name, false)

    // Check that the objects aren't already connected
    if (terminalA.propElectricalConnection.get.isAtMaxConnections()) {
      terminalA match {
        case t:Terminal => { return (t.name + " on " + t.parentObject.name + " is already connected, and must be disconnected before it can be connected to something else", false) }
        case _ => { return (terminalA.name + " is already connected, and must be disconnected before it can be connected to something else", false) }
      }
    }
    if (terminalB.propElectricalConnection.get.isAtMaxConnections()) {
      terminalB match {
        case t:Terminal => { return (t.name + " on " + t.parentObject.name + " is already connected, and must be disconnected before it can be connected to something else", false) }
        case _ => { return (terminalB.name + " is already connected, and must be disconnected before it can be connected to something else", false) }
      }
    }

    // TODO: Check that A and B are in the same container?


    // If we reach here, the checks have passed
    return ("", true)
  }

  // Check to make sure a terminal reference is valid.
  // Return signature is (terminal, errorString, success)
  def getTerminal(_terminalIn:EnvObject):(EnvObject, String, Boolean) = {
    var terminalIn = _terminalIn

    terminalIn match {
      case x:Terminal => { return (terminalIn, "", true) }    // Valid/Good
      case x:PolarizedElectricalComponent => { return (terminalIn, "Connections must specify specific points of contact on polarized electrical components (e.g. anode, cathode)", false) }
      case x:UnpolarizedElectricalComponent => { return (terminalIn, "Connections must specify specific points of contact on unpolarized electrical components (e.g. terminal 1, terminal 2)", false) }
      case x:EnvObject => {
        // Case: Not an object with terminals to connect to
        if (!x.hasUnpolarizedElectricalTerminals()) return (terminalIn, "It's not clear how to connect something to " + x.name, false)
        val unconnectedTerminal = x.getUnconnectedElectricalTerminal()
        // Case: An object with terminals that are already used
        if (unconnectedTerminal.isEmpty) return (terminalIn, x.name + " is already connected, and must be disconnected before it can be connected to something else", false)
        // Case: An object with a free terminal
        terminalIn = unconnectedTerminal.get
        return (terminalIn, "", true)
      }
    }
  }

  def generatePossibleValidActions(agent:EnvObject, visibleObjects:Array[EnvObject], uuid2referentLUT:Map[Long, String]):Array[PossibleAction] = {
    val out = new ArrayBuffer[PossibleAction]()

    for (obj1 <- visibleObjects) {
      for (obj2 <- visibleObjects) {
        // Pack for check
        val assignments = Map(
          "agent" -> agent,
          "terminalA" -> obj1,
          "terminalB" -> obj2
        )

        // Do check
        if (this.isValidAction(assignments)._2 == true) {
          // Pack and store
          val pa = new PossibleAction(Array[ActionExpr](
            new ActionExprText("connect"),
            new ActionExprObject(obj1, referent = uuid2referentLUT(obj1.uuid)),
            new ActionExprText("to"),
            new ActionExprObject(obj2, referent = uuid2referentLUT(obj2.uuid))
          ), this.ACTION_ID)
          out.append(pa)
        }
      }
    }

    return out.toArray
  }

}


class ActionDisconnectElectrical(action:ActionRequestDef, assignments:Map[String, EnvObject]) extends Action(action, assignments) {

  override def runAction(): (String, Boolean) = {
    val agent = assignments("agent")
    val obj = assignments("obj")

    // Do checks for valid action
    val (invalidStr, isValid) = ActionDisconnectElectrical.isValidAction(assignments)
    if (!isValid) return (invalidStr, false)

    // Do disconnection
    obj match {
      case x:EnvObject => {
        x.disconnectElectricalTerminals()
        return (x.name + " has been disconnected", false)
      }
    }

  }

}

object ActionDisconnectElectrical {
  val ACTION_NAME = "disconnect electrically"
  val ACTION_ID   = ActionDefinitions.ACTION_ID_DISCONNECT
  val isOracleAction = false

  def registerAction(actionHandler:ActionHandler) {
    // Action: Move
    val triggerPhrase = new ActionTrigger(List(
      new ActionExprOR(List("disconnect")),
      new ActionExprIdentifier("obj"),
    ))
    val action = mkActionRequest(ACTION_NAME, triggerPhrase, ACTION_ID, isOracleAction = isOracleAction)
    actionHandler.addAction(action)

  }

  def isValidAction(assignments:Map[String, EnvObject]): (String, Boolean) = {
    val agent = assignments("agent")
    val obj = assignments("obj")

    // Check 1: Check that agent is valid
    agent match {
      case a:Agent => { }
      case _ => return ("I'm not sure what that means", false)
    }

    // Check 2:
    obj match {
      case x:Terminal => {
        return ("You must disconnect entire objects (such as " + x.parentObject.name + ") instead of just single terminals", false)
      }
      case x:EnvObject => {
        return ("", true)
      }
      case _ => return ("It's not clear how to disconnect that", false)
    }

    return (Action.MESSAGE_UNKNOWN_CATCH, false)
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
          new ActionExprText("disconnect"),
          new ActionExprObject(obj, referent = uuid2referentLUT(obj.uuid))
        ), this.ACTION_ID)
        out.append(pa)
      }
    }

    return out.toArray
  }

}
