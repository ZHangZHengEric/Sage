package language.model

import scala.collection.mutable
import scala.util.parsing.input.Positional

case class ClassDef(val name:String, val superclass:String, val constructorDef:ConstructorDef, val propertyDefaults:List[PropertyDefault], val propertyFunctions:List[PropertyFunction]) extends Statement {
  val propertyFunctionLUT:Map[String, PropertyFunction] = this.mkPropertyFunctionLUT(propertyFunctions)

  def mkPropertyFunctionLUT(in:List[PropertyFunction]):Map[String, PropertyFunction] = {
    val out = mutable.Map[String, PropertyFunction]()

    for (propFunct <- in) {
      out(propFunct.propName) = propFunct
    }

    out.toMap
  }

  override def toString():String = {
    val os = new StringBuilder

    os.append("Class(")
    os.append("Name: " + name + ", ")
    os.append("Superclass: " + superclass + ", ")
    os.append("Property Functions: " + propertyFunctions.mkString(", "))
    os.append(")")

    os.toString()
  }
}

case class ConstructorDef(val paramSigList:ParamSigList, val statements:Option[List[Statement]]) extends Positional {

  override def toString():String = {
    val os = new StringBuilder

    os.append("ConstructorDef(")
    os.append("ParamSigList: " + paramSigList.toString() + ", ")
    os.append("Statements: " + statements.toString)
    os.append(")")

    os.toString()
  }
}

case class PropertyFunction(val propName:String, val isOverride:Boolean, val calculateAtRuntime:Boolean, val codeblock:List[Statement]) extends Positional {

  override def toString():String = {
    val os = new StringBuilder

    os.append("PropertyFunction(")
    os.append("PropName: " + propName + ", ")
    os.append("isOverride: " + isOverride + ", ")
    os.append("CalculateAtRuntime: " + calculateAtRuntime + ", ")
    os.append("Codeblock: " + codeblock.mkString(", "))
    os.append(")")

    os.toString()
  }

}

case class PropertyDefault(val propName:String, valueExpr:Expr) extends Positional {

  override def toString():String = {
    val os = new StringBuilder

    os.append("PropertyDefault(")
    os.append("PropName: " + propName + ", ")
    os.append("ValueExpr: " + valueExpr.toString + ", ")
    os.append(")")

    os.toString()
  }


}
