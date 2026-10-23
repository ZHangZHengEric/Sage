package language.model

import scala.util.parsing.input.Positional

case class RuleDef(val name:String, val paramSigList:ParamSigList, val preconditions:List[PredicateRef], val postconditions:List[PredicateRef]) extends Statement {

  override def toString():String = {
    val os = new StringBuilder

    os.append("PredicateDef(")
    os.append("Name: " + name + ", ")
    os.append("ParamSigList: " + paramSigList.toString() + ", ")
    os.append("Preconditions: " + preconditions.toString() + ", ")
    os.append("Postconditions: " + postconditions.toString())
    os.append(")")

    // Return
    os.toString()
  }

}

case class PredicateRef(val name:String, val paramList:ParamList) extends Positional {

  override def toString():String = {
    val os = new StringBuilder

    os.append("PredicateRef(")
    os.append("Name: " + name + ", ")
    os.append("ParamList: " + paramList)
    os.append(")")

    // Return
    os.toString()
  }

}

case class ParamList(val parameters:List[Param]) extends Positional {

  override def toString():String = {
    val os = new StringBuilder

    os.append("ParamList(" + parameters.toString() + ")")

    // Return
    os.toString()
  }
}

case class Param(val name:String, val value:String) extends Positional {

  override def toString():String = {
    val os = new StringBuilder

    os.append("Param(name: " + name + " value: " + value + ")")

    // Return
    os.toString()
  }
}
