package language.model

import scala.util.parsing.input.Positional

class Loop extends Statement {

}

// Conventional for loop (e.g. for (i <- 0 until 10 by 2) )
case class ForLoop(val varName:String, val range:ForRange, val statements:List[Statement]) extends Statement {

  override def toString():String = {
    val os = new StringBuilder

    os.append("ForLoop(")
    os.append("VarName: " + varName + ", ")
    os.append("ForRange: " + range.toString() + ", ")
    os.append("Statements: " + statements.mkString(", "))
    os.append(")")

    os.toString()
  }
}


// Special case: For loop that iterates through an object's contained objects
case class ForLoopArrayElem(val varName:String, val arrayExpr:Expr, val statements:List[Statement]) extends Statement {

  override def toString():String = {
    val os = new StringBuilder

    os.append("ForLoopArrayElem(")
    os.append("VarName: " + varName + ", ")
    os.append("arrayExpr: " + arrayExpr + ", ")
    os.append("Statements: " + statements.mkString(", "))
    os.append(")")

    os.toString()
  }
}


case class ForRange(val startIdx:Expr, val until:Expr, val by:Option[Expr]) extends Positional {

  override def toString():String = {
    val os = new StringBuilder

    os.append("ForRange(")
    os.append("StartIdx: " + startIdx + ", ")
    os.append("Until: " + until + ", ")
    os.append("By: " + by)
    os.append(")")

    os.toString()
  }

}

class ForRangeParsed(val startIdx:Int, val until:Int, val by:Int) {
  def this() = this(0, 0, 0)

  override def toString():String = {
    val os = new StringBuilder

    os.append("ForRange(")
    os.append("StartIdx: " + startIdx + ", ")
    os.append("Until: " + until + ", ")
    os.append("By: " + by)
    os.append(")")

    os.toString()
  }

}
