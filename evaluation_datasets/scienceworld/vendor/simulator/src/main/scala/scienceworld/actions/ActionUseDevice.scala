package scienceworld.actions

import language.model.{ActionExpr, ActionExprIdentifier, ActionExprOR, ActionExprObject, ActionExprText, ActionRequestDef, ActionTrigger}
import scienceworld.input.ActionDefinitions.mkActionRequest
import scienceworld.input.{ActionDefinitions, ActionHandler}
import scienceworld.objects.agent.Agent
import scienceworld.objects.devices.Device
import scienceworld.struct.EnvObject

import scala.collection.mutable.ArrayBuffer

/*
 * Action: Use device
 */
class ActionUseDevice(action:ActionRequestDef, assignments:Map[String, EnvObject]) extends Action(action, assignments) {

  override def runAction(): (String, Boolean) = {
    val agent = assignments("agent")
    val device = assignments("device")
    val patientObj = assignments("patient")

    // Do checks for valid action
    val (invalidStr, isValid) = ActionUseDevice.isValidAction(assignments)
    if (!isValid) return (invalidStr, false)

    // Use the device on the patient object
    val (success, resultStr) = device.useWith(patientObj)
    if (!success) return ("I'm not sure how to use those two things together.", false)      //## TODO: Elegant way of handling this with checks?

    return (resultStr, true)
  }

}

object ActionUseDevice {
  val ACTION_NAME = "use object"
  val ACTION_ID   = ActionDefinitions.ACTION_ID_USEDEVICE
  val isOracleAction = false

  def registerAction(actionHandler:ActionHandler) {
    // Action: Move
    val triggerPhrase = new ActionTrigger(List(
      new ActionExprOR(List("use")),
      new ActionExprIdentifier("device"),
      new ActionExprOR(List("on", "with")),
      new ActionExprIdentifier("patient")
    ))
    val action = mkActionRequest(ACTION_NAME, triggerPhrase, ACTION_ID, isOracleAction = isOracleAction)
    actionHandler.addAction(action)

  }

  def isValidAction(assignments:Map[String, EnvObject]): (String, Boolean) = {
    val agent = assignments("agent")
    val device = assignments("device")
    val patientObj = assignments("patient")

    // Check 1: Check that agent is valid
    agent match {
      case a:Agent => { }
      case _ => return ("I'm not sure what that means", false)
    }

    // Check 2: Check that the device is a device
    if ((!device.propDevice.isDefined) || (!device.propDevice.get.isUsable)) {
      return ("I'm not sure how to use the " + device.name + ". ", false)
    }

    //TODO: Check 3: Check that using the device on that thing is valid?

    // Checks complete -- if we reach here, the action is valid
    return ("", true)
  }

  def generatePossibleValidActions(agent:EnvObject, visibleObjects:Array[EnvObject], uuid2referentLUT:Map[Long, String]):Array[PossibleAction] = {
    val out = new ArrayBuffer[PossibleAction]()

    for (obj1 <- visibleObjects) {
      for (obj2 <- visibleObjects) {
        // Pack for check
        val assignments = Map(
          "agent" -> agent,
          "device" -> obj1,
          "patient" -> obj2
        )

        // Do check
        if (this.isValidAction(assignments)._2 == true) {
          // Pack and store
          val pa = new PossibleAction(Array[ActionExpr](
            new ActionExprText("use"),
            new ActionExprObject(obj1, referent = uuid2referentLUT(obj1.uuid)),
            new ActionExprText("on"),
            new ActionExprObject(obj2, referent = uuid2referentLUT(obj2.uuid))
          ), this.ACTION_ID)
          out.append(pa)
        }
      }
    }

    return out.toArray
  }
}
