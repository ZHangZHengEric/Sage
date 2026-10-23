package scienceworld.actions

import language.model.{ActionExpr, ActionExprIdentifier, ActionExprOR, ActionExprObject, ActionRequestDef, ActionTrigger}
import scienceworld.input.ActionDefinitions.mkActionRequest
import scienceworld.input.ActionHandler
import scienceworld.runtime.pythonapi.TemplateAction
import scienceworld.struct.EnvObject

import scala.collection.mutable.ArrayBuffer

class Action(val action:ActionRequestDef, val assignments:Map[String, EnvObject]) {
  def name:String = action.name

  // Returns (User error message (if applicable), whether the action could be executed or not)
  def isValidAction():(String, Boolean) = {
    throw new RuntimeException("ERROR: Action.isValidAction() base class method called.")
    return ("error message", false)
  }

  // Returns: (User message, whether the action was successful or not)
  def runAction():(String, Boolean) = {
    throw new RuntimeException("ERROR: Action.runAction() base class method called.")
    return ("Empty action (" + this.name + ").", false)
  }

}


object Action {
  val MESSAGE_UNKNOWN_CATCH       = "<unknown catch>"
}



class PossibleAction(val sequence:Array[ActionExpr], templateID:Int) {

  def mkHumanReadableStr():String = {
    return sequence.map(_.mkHumanReadableExample()).mkString(" ")
  }

  // Export into a TemplateAction storage class
  def toTemplate():TemplateAction = {
    // Step 1: Get sanitized plain-text string
    val sanitizedStr = this.mkHumanReadableStr()

    // Step 2: Collect objects
    val objects = new ArrayBuffer[EnvObject]
    for (elem <- this.sequence) {

      elem match {
        case e:ActionExprObject => {
          objects.append( e.obj )
        }
        case _ => {
          // Ignore
        }
      }

    }

    // Step 3: Get object IDs
    val objectIDs = objects.map(_.uuid.toInt).toList
    val objectTypes = objects.map(_.typeID.toInt).toList

    // Return
    new TemplateAction(sanitizedStr, templateID, objectIDs, objectTypes)
  }


  override def toString():String = {
    this.mkHumanReadableStr()
  }
}
