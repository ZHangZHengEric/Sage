package scienceworld.objects.devices

import scienceworld.objects.substance.Water
import scienceworld.properties.{GlassProp, IsActivableDeviceOff, IsNotContainer, IsOpenUnclosableContainer, IsUsable, MoveableProperties, SteelProp}
import scienceworld.struct.EnvObject

class Thermometer extends Device {
  this.name = "thermometer"

  this.propMaterial = Some(new GlassProp())
  this.propContainer = Some( new IsNotContainer() )
  this.propDevice = Some(new IsUsable())
  this.propMoveable = Some(new MoveableProperties(isMovable = true))

  def getDeviceReading(obj:EnvObject): Option[String] = {
    if (!obj.propMaterial.isDefined) return None

    // Get temperature
    val objTemp = obj.propMaterial.get.temperatureC
    // Convert to rounded string
    return Some(objTemp.formatted("%.0f") + " degrees celsius")
  }


  override def useWith(patientObj:EnvObject):(Boolean, String) = {
    val currentMeasurement = this.getDeviceReading(patientObj)
    if (currentMeasurement.isEmpty) return (true, "That thing doesn't appear to have a temperature that the thermometer can read. ")

    return (true, "the thermometer measures a temperature of " + currentMeasurement.get)
  }

  override def getReferents(): Set[String] = {
    Set("thermometer", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder

    // Get reading of the thermometer's current container
    var currentMeasurement:Option[String] = None
    /*
    if (this.getContainer().isDefined) {
      currentMeasurement = this.getDeviceReading( this.getContainer().get )
    }
     */

    // Get reading of the thermometer (itself's) current temperature
    currentMeasurement = this.getDeviceReading( this )

    if (currentMeasurement.isDefined) {
      os.append("a " + this.getDescriptName() + ", currently reading a temperature of " + currentMeasurement.get)
    } else {
      os.append("a " + this.getDescriptName())
    }

    os.toString
  }

}
