package scienceworld.objects.devices

import scienceworld.processes.{Combustion, Shovelling}
import scienceworld.properties.{HeatSourcePropertiesLighter, HeatSourcePropertiesStove, IsNotContainer, IsOpenUnclosableContainer, IsUsableNonActivable, MetalProp, MoveableProperties}
import scienceworld.struct.EnvObject
import util.StringHelpers

class Lighter extends HeatSource {
  this.name = "lighter"

  this.propHeatSource = Some(new HeatSourcePropertiesLighter)
  this.propMaterial = Some(new MetalProp())
  this.propContainer = Some( new IsNotContainer() )
  this.propDevice = Some(new IsUsableNonActivable())
  this.propMoveable = Some(new MoveableProperties(isMovable = true))


  // Instantaneously heat something for a short while
  override def useWith(patientObj:EnvObject):(Boolean, String) = {
    // Check material properties
    if (patientObj.propMaterial.isEmpty) return (true, "It's not clear how to use those items together.")

    val combustionTemp = patientObj.propMaterial.get.combustionPoint
    val heatsourceTemp = this.propHeatSource.get.maxTemp

    if (combustionTemp <= heatsourceTemp) {
      // Combust the object
      println ("TODO: Combust")
      val (success, messageStr) = Combustion.setObjectOnFire(patientObj)

      return (true, messageStr)

    } else {
      // Heat up the object a small amount
      val heatAmount = 10.0f
      // Calculate the amount to heat up the object
      var delta = heatsourceTemp - patientObj.propMaterial.get.temperatureC
      if (delta > heatAmount) delta = heatAmount
      if (delta + patientObj.propMaterial.get.temperatureC > heatsourceTemp) delta = heatsourceTemp - patientObj.propMaterial.get.temperatureC
      if (delta < 0) delta = 0.0f
      // Do the heating
      patientObj.propMaterial.get.temperatureC += delta

      return (true, "The lighter heats up the " + patientObj.name + " a small amount.")
    }

  }


  override def tick():Boolean = {
    // If it's activated, then set max temp.  If deactivated, set temp to off.
    if (this.propDevice.isDefined) {
      if (this.propDevice.get.isActivated) {
        this.propHeatSource.get.setOnMax()
      } else {
        this.propHeatSource.get.setOff()
      }
    }

    super.tick()
  }

  override def getReferents():Set[String] = {
    Set("lighter", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int):String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName())

    os.toString()
  }

}
