package language.model

case class Return(expr:Expr) extends Statement {

  override def toString():String = {
    val os = new StringBuilder

    os.append("Return(")
    os.append("Expr: " + expr)
    os.append(")")

    // Return
    os.toString()
  }
}
