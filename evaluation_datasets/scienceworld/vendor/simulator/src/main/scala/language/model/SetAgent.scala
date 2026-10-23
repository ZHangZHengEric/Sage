package language.model

case class SetAgent(expr:Expr) extends Statement {

  override def toString():String = {
    return "SetAgent(expr: " + expr + ")"
  }
}
