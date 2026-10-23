package language.model

import scala.collection.mutable
import scala.util.parsing.input.Positional

case class PredicateDef(val name:String, val paramSigList:ParamSigList, val statements:Option[List[Statement]], val getter:Option[List[Statement]], val setter:Option[List[Statement]]) extends Statement {

  def getVarType(varName:String):String = {
    paramSigList.getVarType(varName)
  }

  override def toString():String = {
    val os = new StringBuilder

    os.append("PredicateDef(")
    os.append("Name: " + name + ", ")
    os.append("ParamSigList: " + paramSigList.toString() + ", ")
    os.append("Statements: " + statements.toString() + ", ")
    os.append("Getter: " + getter.toString() + ", ")
    os.append("Setter: " + setter.toString() + ", ")
    os.append(")")

    // Return
    os.toString()
  }
}


case class ParamSigList(val parameters:List[ParamSig]) extends Positional {
  val paramLUT = this.mkParamLUT(parameters)

  // Get the type of a variable with a given name
  def getVarType(varName:String):String = {
    for (param <- parameters) {
      if (param.name == varName) return param.objType
    }
    // Default return
    return ""
  }

  def mkParamLUT(in:List[ParamSig]):Map[String, String] = {
    val out = mutable.Map[String, String]()
    for (param <- in) {
      out(param.name) = param.objType
    }
    // Return
    out.toMap
  }

  override def toString():String = {
    val os = new StringBuilder

    os.append("ParamSigList(" + parameters.toString() + ")")

    // Return
    os.toString()
  }
}

case class ParamSig(val name:String, val objType:String) extends Positional {

  override def toString():String = {
    val os = new StringBuilder

    os.append("ParamSig(name: " + name + " objType: " + objType + ")")

    // Return
    os.toString()
  }
}
