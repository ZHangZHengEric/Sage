package scienceworld.processes

import scienceworld.struct.EnvObject

class HeatTransfer {

}

object HeatTransfer {
  val HEAT_TRANSFER_COEFFICIENT = 0.10
  val MAX_TRANSFER_PER_STEP     = 1000.0f   // Maximum temperature differential to transfer per tick (e.g. 50c)
  //val HEAT_TRANSFER_COEFFICIENT = 0.06

  // Heat transfer between a heat source, and an object being heated by it
  def heatTransferHeatSource(heatSource: EnvObject, heatedObj: EnvObject): Unit = {
    // If this heat source is an activated device, continue.  Or, if it's not a device, we assume always on.
    if ((heatSource.propDevice.isEmpty) || (heatSource.propDevice.isDefined && heatSource.propDevice.get.isActivated == true)) {

      // If the heat source is on (signified by having a set temperature)
      if (heatSource.propHeatSource.get.curSetTemp.isDefined) {
        val heaterTemp = heatSource.propHeatSource.get.curSetTemp.get

        if (heatedObj.propMaterial.isDefined) { // Only continue if the object has physical properties defined
          val objTemp = heatedObj.propMaterial.get.temperatureC
          if (objTemp < heaterTemp) {
            val deltaTemp = heaterTemp - objTemp
            var increment = deltaTemp * HEAT_TRANSFER_COEFFICIENT
            if (math.abs(increment) > MAX_TRANSFER_PER_STEP) increment = MAX_TRANSFER_PER_STEP * increment.signum     // Clip to a maximum of (-MAX_TRANSFER_PER_STEP, +MAX_TRANSFER_PER_STEP)
            heatedObj.propMaterial.get.temperatureC += increment

            //println("Heat transfer: Object (" + heatedObj.name + ") temperature now " + heatedObj.propMaterial.get.temperatureC)
          }
        }

      }
    }

  }


  // Heat transfer between a heat source, and an object being heated by it
  def heatTransferCoolingSource(coolingSource: EnvObject, cooledObj: EnvObject): Unit = {
    // If this heat source is an activated device, continue.  Or, if it's not a device, we assume always on.
    if ((coolingSource.propDevice.isEmpty) || (coolingSource.propDevice.isDefined && coolingSource.propDevice.get.isActivated == true)) {

      // If the heat source is on (signified by having a set temperature)
      if (coolingSource.propCoolingSource.get.curSetTemp.isDefined) {
        val coolerTemp = coolingSource.propCoolingSource.get.curSetTemp.get

        if (cooledObj.propMaterial.isDefined) { // Only continue if the object has physical properties defined
          val objTemp = cooledObj.propMaterial.get.temperatureC
          if (objTemp > coolerTemp) {
            val deltaTemp = coolerTemp - objTemp
            var increment = deltaTemp * HEAT_TRANSFER_COEFFICIENT
            if (math.abs(increment) > MAX_TRANSFER_PER_STEP) increment = MAX_TRANSFER_PER_STEP * increment.signum     // Clip to a maximum of (-MAX_TRANSFER_PER_STEP, +MAX_TRANSFER_PER_STEP)
            cooledObj.propMaterial.get.temperatureC += increment

            //println("Heat transfer: Object (" + cooledObj.name + ") temperature now " + cooledObj.propMaterial.get.temperatureC)
          }
        }

      }
    }

  }


  // Conductive heat transfer between two touching objects
  def heatTransferTouchingObjects(obj1:EnvObject, obj2:EnvObject): Unit = {
    // Make sure object material properties are defined, or we can't calculate heat transfer
    if ((obj1.propMaterial.isEmpty) || (obj2.propMaterial.isEmpty)) return

    val obj1Prop = obj1.propMaterial.get
    val obj2Prop = obj2.propMaterial.get

    val obj1Temp = obj1Prop.temperatureC
    val obj2Temp = obj2Prop.temperatureC

    val minThermalConductivity = math.min(obj1Prop.thermalConductivity, obj2Prop.thermalConductivity)

    // Delta between obj1 and obj2
    val delta1 = (obj2Prop.temperatureC - obj1Prop.temperatureC) * minThermalConductivity
    var increment1 = delta1 * HEAT_TRANSFER_COEFFICIENT
    if (math.abs(increment1) > MAX_TRANSFER_PER_STEP) increment1 = MAX_TRANSFER_PER_STEP * increment1.signum     // Clip to a maximum of (-MAX_TRANSFER_PER_STEP, +MAX_TRANSFER_PER_STEP)
    obj1.propMaterial.get.temperatureC += increment1

    // Delta between obj2 and obj1
    val delta2 = (obj1Prop.temperatureC - obj2Prop.temperatureC) * minThermalConductivity
    var increment2 = delta2 * HEAT_TRANSFER_COEFFICIENT
    if (math.abs(increment2) > MAX_TRANSFER_PER_STEP) increment2 = MAX_TRANSFER_PER_STEP * increment2.signum     // Clip to a maximum of (-MAX_TRANSFER_PER_STEP, +MAX_TRANSFER_PER_STEP)
    obj2.propMaterial.get.temperatureC += increment2

    //println ("Heat transfer (conductive - 1): Object (" + obj1.name + ") temperature from " + obj1Temp + " to " + obj1.propMaterial.get.temperatureC)
    //println ("Heat transfer (conductive - 2): Object (" + obj2.name + ") temperature from " + obj1Temp + " to " + obj2.propMaterial.get.temperatureC)
  }


}
