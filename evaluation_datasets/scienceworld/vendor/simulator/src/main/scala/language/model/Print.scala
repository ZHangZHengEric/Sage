package language.model


case class Print(expr:Expr) extends Statement {

  override def toString():String = {
    val os = new StringBuilder

    os.append("Print(Expr: " + expr.toString() + ")")

    // Return
    os.toString()
  }

}

case class PrintLog(expr:Expr) extends Statement {

  override def toString():String = {
    val os = new StringBuilder

    os.append("PrintLog(Expr: " + expr.toString() + ")")

    // Return
    os.toString()
  }

}
