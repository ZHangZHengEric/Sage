package language.model

import scala.util.parsing.input.Positional

class Expr() extends Positional {

  def toStringCode():String = ""        // A string formatted in the same way the user would enter it, for error messages/user debugging
}

case class Number(val value:Double) extends Expr {
  override def toString():String = "Double(value: " + value + ")"
  override def toStringCode():String = value.toString
}

case class Str(value:String) extends Expr {
  override def toString():String = "String(value: " + value + ")"
  override def toStringCode():String = "\"" + value.toString + "\""
}

object Str {
  def interpretStringControlChars(inStr:String):String = {
    var outStr = inStr
    outStr = outStr.replaceAll("\\\\n", "\n")
    outStr = outStr.replaceAll("\\\\r", "\r")
    outStr = outStr.replaceAll("\\\\t", "\t")
    // Return
    return outStr
  }

  def desanitizeStrControlChars(inStr:String):String = {
    var outStr = inStr
    outStr = outStr.replaceAll("\\n", "\\n")
    outStr = outStr.replaceAll("\\r", "\\r")
    outStr = outStr.replaceAll("\\t", "\\t")
    // Return
    return outStr
  }

}

case class Bool(val value:Boolean) extends Expr {
  override def toString():String = "Boolean(value: " + value + ")"
  override def toStringCode():String = value.toString
}

case class Identifier(val name:String) extends Expr {
  override def toString():String = "Identifier(name: " + name + ")"
  override def toStringCode():String = name.toString
}

case class ObjectProperty(val name:String, val property:String) extends Expr {
  override def toString():String = return "ObjectProperty(name: " + name + ", property: " + property + ")"
  override def toStringCode():String = name + "." + property
}

case class ArrayDef(val elems:List[Expr]) extends Expr {
  override def toString():String = return "ArrayDef(elems: " + elems.mkString(", ") + ")"
  override def toStringCode():String = "Array(" + elems.map(_.toStringCode()).mkString(", ") + ")"
}

case class ArrayElem(val name:String, val elemIdxExpr:Expr) extends Expr {
  override def toString():String = return "ArrayElem(name: " + name + ", elemIdxExpr: " + elemIdxExpr + ")"
  override def toStringCode():String = name + "(" + elemIdxExpr.toStringCode() + ")"
}

case class NegatedExpr(val expr:Expr) extends Expr {
  override def toString():String = return "NegatedExpr(Expr: " + expr + ")"
  override def toStringCode():String = "!" + expr.toStringCode()
}

case class Operator(var op:String, var left:Expr, var right:Expr) extends Expr {

  override def toString():String = {
    val os = new StringBuilder

    os.append("Operator(")
    os.append("Left: " + left.toString + ", ")
    os.append("Operator: " + op.toString + ", ")
    os.append("Right: " + right.toString)
    os.append(")")

    return os.toString()
  }

  override def toStringCode():String = left.toStringCode() + " " + op + " " + right.toStringCode()
}

// Creating a new object instance
case class ObjectCreate(val objType:String, val objName:String, val paramList:ParamList) extends Expr {

  override def toString():String = {
    val os = new StringBuilder

    os.append("ObjectCreate(")
    os.append("ObjType: " + objType + ", ")
    os.append("ObjName: " + objName + ", ")
    os.append("ParamList: " + paramList)
    os.append(")")

    // Return
    os.toString()
  }

  override def toStringCode():String = "new " + objType        //## TODO
}

case class BuiltInFunction(var function:String, var args:List[Expr]) extends Expr {

  override def toString():String = {
    val os = new StringBuilder

    os.append("BuiltInFunction(")
    os.append("Function: " + function + ", ")
    os.append("Args: " + args.mkString(", "))
    os.append(")")

    // Return
    os.toString()
  }

  override def toStringCode():String = function + "(" + args.map(_.toStringCode()).mkString(", ") + ")"
}
