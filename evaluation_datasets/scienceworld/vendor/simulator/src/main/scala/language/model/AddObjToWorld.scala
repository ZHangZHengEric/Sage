package language.model

case class AddObjToWorld (expr:Expr) extends Statement {

  override def toString():String = {
    val os = new StringBuilder
    os.append("AddObjToWorld(Expr: " + expr.toString() + ")")
    // Return
    os.toString()
  }

}


case class DeleteObject(expr:Expr) extends Statement {

  override def toString():String = {
    val os = new StringBuilder
    os.append("DeleteObject(Expr: " + expr.toString() + ")")
    // Return
    os.toString()
  }

}


case class MoveObject (objExpr:Expr, moveToExpr:Expr) extends Statement {

  override def toString():String = {
    val os = new StringBuilder

    os.append("moveObject(objExpr: " + objExpr.toString() + ", moveToExpr: " + moveToExpr.toString + ")")

    // Return
    os.toString()
  }

}
