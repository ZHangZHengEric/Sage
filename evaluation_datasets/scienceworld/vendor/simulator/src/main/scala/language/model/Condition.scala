package language.model

class Condition {

}

// A condition (e.g. X == Y)
case class ConditionLR(val op:String, val left:Expr, val right:Expr) extends Condition {

  override def toString():String = {
    val os = new StringBuilder

    os.append("ConditionLR(left: " + left.toString() + " operator: " + op.toString() + " right: " + right.toString() + ")")
    // Return
    os.toString()
  }
}


class ConditionExpr() {

}

// Multiple conditional expressions bound with AND and OR operators (e.g. (X == Y) && (A == B) )
case class ConditionOperator(op:String, var left:ConditionExpr, var right:ConditionExpr) extends ConditionExpr {

  override def toString(): String = {
    val os = new StringBuilder

    os.append("ConditionOperator(op: " + op + " left: " + left + " right: " + right + ")")

    // Return
    os.toString()
  }

}

case class ConditionElem(condition:Condition) extends ConditionExpr {

  override def toString(): String = {
    val os = new StringBuilder

    os.append("ConditionElem(" + condition + ")")

    // Return
    os.toString()
  }

}
