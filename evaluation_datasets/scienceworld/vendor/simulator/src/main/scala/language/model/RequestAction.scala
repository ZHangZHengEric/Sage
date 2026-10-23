package language.model

case class RequestAction(val actionRef:PredicateRef) extends Statement {

  override def toString():String = {
    val os = new StringBuilder

    os.append("RequestAction(")
    os.append("actionRef: " + actionRef)
    os.append(")")

    // Return
    os.toString()
  }

}
