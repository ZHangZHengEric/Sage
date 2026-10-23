package language.struct

import language.model.RuleDef

/*
 * Storage classes for keeping track of changes that happen to the state space
 */

trait ChangeLog {

  def toHTML():String

}

class ChangeLogObjProp(val obj:EnvObject, prop:String, valueFrom:String, valueTo:String) extends ChangeLog {
  val objStr = obj.toString()
  val objName = obj.getName()
  val objType = obj.getType()
  val objUUID = obj.uuid

  def toHTML():String = {
    val os = new StringBuilder
    os.append("<td style=\"width:300px\"> Obj(" + objUUID + "/" + objName + "/" + objType + ") </td>")
    os.append("<td style=\"width:200px\"> " + prop + "</td>")
    os.append("<td style=\"width:200px\"> " + valueFrom + " </td>")
    os.append("<td style=\"width:200px\"> " + valueTo + " </td>")
    // Return
    os.toString()
  }

  override def toString():String = {
    return "ChangeLogObjProp: Obj(" + objUUID + "/" + objName + "/" + objType + "): Property (" + prop +") changed from (" + valueFrom + ") to (" + valueTo + ")"
  }
}

class ChangeLogObjMove(val obj:EnvObject, val objOldContainer:Option[EnvObject], val objNewContainer:Option[EnvObject]) extends ChangeLog {
  val objStr = obj.toString()
  val objName = obj.getName()
  val objType = obj.getType()
  val objUUID = obj.uuid

  val objOldContainerStr = if (objOldContainer.isDefined) objOldContainer.get.toString() else "None"
  val objOldContainerName = if (objOldContainer.isDefined) objOldContainer.get.getName() else "None"
  val objOldContainerType = if (objOldContainer.isDefined) objOldContainer.get.getType() else "None"
  val objOldContainerUUID = if (objOldContainer.isDefined) objOldContainer.get.uuid else "None"

  val objNewContainerStr = if (objNewContainer.isDefined) objNewContainer.get.toString() else "None"
  val objNewContainerName = if (objNewContainer.isDefined) objNewContainer.get.getName() else "None"
  val objNewContainerType = if (objNewContainer.isDefined) objNewContainer.get.getType() else "None"
  val objNewContainerUUID = if (objNewContainer.isDefined) objNewContainer.get.uuid else "None"


  def toHTML():String = {
    val os = new StringBuilder
    os.append("<td style=\"width:300px\"> Obj(" + objUUID + "/" + objName + "/" + objType + ") </td>")
    os.append("<td style=\"width:300px\"> container Object(" + objOldContainerUUID + "/" + objOldContainerName + "/" + objOldContainerType + ") </td>")
    os.append("<td style=\"width:300px\"> to Object(" + objNewContainerUUID + "/" + objNewContainerName + "/" + objNewContainerType + ") </td>")
    // Return
    os.toString()
  }

  override def toString():String = {
    val os = new StringBuilder
    os.append("ChangeLogObjMove: Moved Object(" + objUUID + "/" + objName + "/" + objType + ") ")
    os.append("from container Object(" + objOldContainerUUID + "/" + objOldContainerName + "/" + objOldContainerType + ") ")
    os.append("to container Object(" + objNewContainerUUID + "/" + objNewContainerName + "/" + objNewContainerType + ") ")
    return os.toString()
  }
}

class RuleChangeLog(val rule:RuleDef, val changes:Array[ChangeLog]) {

  def toHTML(ruleNum:String = ""):String = {
    val os = new StringBuilder

    os.append("<table><tr>")

    var fontColor = "black"
    if (changes.length == 0) fontColor = "lightgrey"
    var bgColor = "lightgrey"
    if (changes.length == 0) bgColor = "white"

    os.append("<tr><th style=\"width:30px;background-color:" + bgColor + "\"><font color=" + fontColor + ">" + ruleNum + " </font></th>")
    os.append("<th colspan=\"5\" style=\"background-color:" + bgColor + "\"><font color=" + fontColor + ">Rule: " + rule.name + " </font></td></th></tr>")
    for (i <- 0 until changes.length) {
      os.append("<tr><td width=30px></td><td>" + i + "</td>" + changes(i).toHTML() + "</tr>")
    }

    os.append("</tr></table>")

    os.toString()
  }

  override def toString():String = {
    val os = new StringBuilder
    os.append("Rule: " + rule.name + "\t" + rule.toString() + "\n")
    os.append("Changes (" + changes.length + "):\n")
    for (i <- 0 until changes.length) {
      os.append("\t" + i + ": " + changes(i).toString + "\n")
    }
    os.toString()
  }

}
