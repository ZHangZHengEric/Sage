package scienceworld.objects.devices

import scienceworld.objects.substance.Water
import scienceworld.properties.{IsActivableDeviceOff, IsOpenUnclosableContainer, MoveableProperties, SteelProp}
import scienceworld.struct.EnvObject

class Device extends EnvObject {
  this.name = "device"

  this.propDevice = Some(new IsActivableDeviceOff())

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + ", which is turned ")
    if (this.propDevice.get.isActivated) { os.append("on") } else { os.append("off") }

    os.toString
  }

}
