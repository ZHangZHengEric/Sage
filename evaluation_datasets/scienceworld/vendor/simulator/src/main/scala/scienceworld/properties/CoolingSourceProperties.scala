package scienceworld.properties


class CoolingSourceProperties(var minTemp:Double, var curSetTemp:Option[Double]) {

  def setOnMin(): Unit = {
    curSetTemp = Some(minTemp)
  }

  def setOff(): Unit = {
    curSetTemp = None
  }


  def toJSON():String = {
    val os = new StringBuilder()
    os.append("{")
    os.append("\"minTemp\":" + this.minTemp + ",")
    os.append("\"curSetTemp\":" + (if (this.curSetTemp.isEmpty) "null" else this.curSetTemp.get))
    os.append("}")

    return os.toString()
  }
}



class CoolingSourcePropertiesFridge extends CoolingSourceProperties(minTemp = 2.0f, curSetTemp = None) {

}

class CoolingSourcePropertiesFreezer extends CoolingSourceProperties(minTemp = -18.0f, curSetTemp = None) {

}

class CoolingSourcePropertiesULTFreezer extends CoolingSourceProperties(minTemp = -86.0f, curSetTemp = None) {

}
