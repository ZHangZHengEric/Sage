package scienceworld.properties

class MoveableProperties(val isMovable:Boolean) {

  def toJSON():String = {
    val os = new StringBuilder()
    os.append("{")
    os.append("\"isMovable\":" + this.isMovable)
    os.append("}")

    return os.toString()
  }

}
