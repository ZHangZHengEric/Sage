package language.model

case class Assignment(val varName:String, val expr:Expr, val firstDefinition:Boolean) extends Statement {
  override def toString():String = "Assignment(varName: " + varName + ", Expr:" + expr.toString + ", FirstDefinition: " + firstDefinition + ")"
}

case class AssignmentObjProp(val objProp:ObjectProperty, val expr:Expr) extends Statement {
  override def toString():String = "AssignmentObjProp(objProp: " + objProp + ", Expr:" + expr.toString + ")"
}

case class AssignmentArrayElem(val arrayElem:ArrayElem, val valueExpr:Expr) extends Statement {
  override def toString():String = "AssignmentArrayElem(ArrayElem: " + arrayElem + ", valueExpr:" + valueExpr.toString + ")"
}
