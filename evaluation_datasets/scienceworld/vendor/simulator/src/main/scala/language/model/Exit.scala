package language.model

case class Exit(exitCode:Int) extends Statement {

  override def toString():String = {
    return "Exit(ExitCode: " + exitCode + ")"
  }
}
