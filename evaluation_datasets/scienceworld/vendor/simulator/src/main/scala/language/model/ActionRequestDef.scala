package language.model

import scienceworld.struct.EnvObject

import scala.collection.mutable
import scala.collection.mutable.ArrayBuffer
import scala.util.parsing.input.Positional

case class ActionRequestDef(val name:String, val paramSigList:ParamSigList, val triggers:List[ActionTrigger], val uniqueActionID:Int, isOracleAction:Boolean = false) extends Statement {

  def getVarType(varName:String):String = {
    paramSigList.getVarType(varName)
  }

  def mkHumanReadableExample():String = {
    if (triggers.length == 0) return ""
    return triggers(0).mkHumanReadableExample()
  }

  override def toString():String = {
    val os = new StringBuilder

    os.append("ActionRequestDef(")
    os.append("Name: " + name + ", ")
    os.append("ParamSigList: " + paramSigList.toString() + ", ")
    os.append("ActionTrigger: " + triggers.mkString(", "))
    os.append(")")

    // Return
    os.toString()
  }

}

object ActionRequestDef {
  def mkBlank():ActionRequestDef = {
    return new ActionRequestDef(name = "", paramSigList = new ParamSigList(parameters = List.empty[ParamSig]), triggers = List.empty[ActionTrigger], uniqueActionID = -1, isOracleAction = false)
  }
}


case class ActionTrigger(val pattern:List[ActionExpr]) extends Positional {

  def mkHumanReadableExample():String = {
    val out = new ArrayBuffer[String]

    for (elem <- pattern) {
      out.append(elem.mkHumanReadableExample())
    }

    out.mkString(" ")
  }

  def mkHumanReadableInstance(varLUT:mutable.Map[String, EnvObject], agentContainer:EnvObject):String = {
    val out = new ArrayBuffer[String]

    for (elem <- pattern) {
      out.append(elem.mkHumanReadableInstance(varLUT, agentContainer))
    }

    out.mkString(" ")
  }

  override def toString():String = {
    val os = new StringBuilder

    os.append("ActionTrigger(")
    os.append("Pattern: " + pattern)
    os.append(")")

    // Return
    os.toString()
  }
}

class ActionExpr() extends Positional {
  def mkHumanReadableExample():String = return ""

  def mkHumanReadableInstance(varLUT:mutable.Map[String, EnvObject], agentContainer:EnvObject):String = return ""
}

case class ActionExprOR(val orElements:List[String]) extends ActionExpr {
  override def mkHumanReadableExample():String = {
    if (orElements.length == 0) return ""
    return orElements(0)      // Return first element
  }

  override def mkHumanReadableInstance(varLUT:mutable.Map[String, EnvObject], agentContainer:EnvObject):String = this.mkHumanReadableExample()

  override def toString():String = return "ActionExprOR(orElements: " + orElements.mkString(",") + ")"
}

case class ActionExprIdentifier(val identifier:String) extends ActionExpr {
  override def mkHumanReadableExample():String = {
    return "OBJ"
  }

  override def mkHumanReadableInstance(varLUT:mutable.Map[String, EnvObject], agentContainer:EnvObject):String = {
    // Look up EnvObject for this identifier
    if (!varLUT.contains(identifier)) return "<UNKNOWN>"
    val obj = varLUT(identifier)

    // Create a plain-text description of the object
    val objDesc = new StringBuilder()
    objDesc.append( obj.getDescriptName() )

    // Add text that describes it's location
    val container = obj.getContainer()
    val containerDescElems = this.mkContainerStrRecursive(container, agentContainer) //TODO
    if (containerDescElems.length > 0) {
      objDesc.append(" (" + containerDescElems.mkString(", ") + ")")
    }

    return objDesc.toString()
  }

  override def toString():String = return "ActionExprIdentifier(identifier: " + identifier + ")"

  // Make the container string (e.g. "in the orange tree, in flower pot 3").
  def mkContainerStrRecursive(curContainer:Option[EnvObject], stopContainer:EnvObject):Array[String] = {
    val out = new ArrayBuffer[String]

    if (curContainer.isDefined) {
      // This
      out.append("in " + curContainer.get.name)
      // Recurse
      if (curContainer.get != stopContainer) {      // Do not continue if we've recursed down to the level of the agent's current container
        out.insertAll(out.length, this.mkContainerStrRecursive(curContainer.get.getContainer(), stopContainer))
      }
    }

    // Return
    return out.toArray
  }

}

// Storage class for holding an object match in PossibleAction
case class ActionExprObject(val obj:EnvObject, val referent:String) extends ActionExpr {
  override def mkHumanReadableExample(): String = {
    //return obj.name
    return referent //+ " (" + obj.getDescriptName() + ")"
  }
}

// Storage class for holding specific text in PossibleAction
case class ActionExprText(val text:String) extends ActionExpr {
  override def mkHumanReadableExample(): String = {
    return text
  }
}
