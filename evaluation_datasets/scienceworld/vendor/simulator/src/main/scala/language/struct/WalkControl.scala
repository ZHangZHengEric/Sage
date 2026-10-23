package language.struct

class WalkControl(val success:Boolean, val returnValue:Option[DynamicValue]) {

  def failed():Boolean = {
    return !success
  }

  def hasReturnValue():Boolean = {
    if (returnValue.isDefined) return true
    // Otherwise
    return false
  }

  override def toString:String = {
    val os = new StringBuilder

    os.append("(")
    os.append("success = " + success + ", ")
    os.append("returnValue = " + returnValue)
    os.append(")")

    // Return
    os.toString()
  }

}


object WalkControl {

  // Generators
  def mkSuccess():WalkControl = {
    new WalkControl(success = true, None)
  }

  def mkReturn(returnValue:DynamicValue):WalkControl = {
    new WalkControl(success = true, Some(returnValue))
  }

  def mkFailure():WalkControl = {
    new WalkControl(success = false, None)
  }

}
