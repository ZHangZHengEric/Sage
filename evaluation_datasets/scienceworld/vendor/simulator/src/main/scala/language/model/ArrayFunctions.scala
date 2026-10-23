package language.model

case class ArrayAppend(val varExpr:Expr, val valueExpr:Expr) extends Statement {
  override def toString():String = "ArrayAppend(varExpr: " + varExpr + ", valueExpr:" + valueExpr.toString + ")"
}

case class ArrayRemove(val varExpr:Expr, val elemExpr:Expr) extends Statement {
  override def toString():String = "ArrayRemove(varExpr: " + varExpr + ", elemExpr:" + elemExpr.toString + ")"
}
