package language.model

case class Define(val name:String, val replaceWith:String) extends Statement {

  override def toString():String = {
    return "Define(name: " + name + ", replaceWith: " + replaceWith + ")"
  }

}
