package scienceworld.properties


class HeatSourceProperties(var maxTemp:Double, var curSetTemp:Option[Double]) {

  def setOnMax(): Unit = {
    curSetTemp = Some(maxTemp)
  }

  def setOff(): Unit = {
    curSetTemp = None
  }


  def toJSON():String = {
    val os = new StringBuilder()
    os.append("{")
    os.append("\"maxTemp\":" + this.maxTemp + ",")
    os.append("\"curSetTemp\":" + (if (this.curSetTemp.isEmpty) "null" else this.curSetTemp.get))
    os.append("}")

    return os.toString()
  }

}



class HeatSourcePropertiesStove extends HeatSourceProperties(maxTemp = 260.0f, curSetTemp = None) {

}

class HeatSourcePropertiesOven extends HeatSourceProperties(maxTemp = 540.0f, curSetTemp = None) {

}

class HeatSourcePropertiesBlastFurnace extends HeatSourceProperties(maxTemp = 3000.0f, curSetTemp = None) {   // A little hotter than normal

}

class HeatSourcePropertiesWoodFire extends HeatSourceProperties(maxTemp = 600.0f, curSetTemp = None) {

}

class HeatSourcePropertiesLighter extends HeatSourceProperties(maxTemp = 2200.0f, curSetTemp = None) {

}
