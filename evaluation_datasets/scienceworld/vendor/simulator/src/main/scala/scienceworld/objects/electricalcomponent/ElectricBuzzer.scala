package scienceworld.objects.electricalcomponent

import scienceworld.objects.electricalcomponent.ElectricalComponent.ROLE_VOLTAGE_USER
import scienceworld.properties.IsNotActivableDeviceOff
import scienceworld.struct.EnvObject.MODE_DETAILED


class ElectricBuzzer() extends PolarizedElectricalComponent {
  this.name = "electric buzzer"

  this.propDevice = Some(new IsNotActivableDeviceOff())

  this.electricalRole = ROLE_VOLTAGE_USER     // Component uses voltage, rather than generating it

  override def tick(): Boolean = {
    super.tick()
  }

  override def getReferents(): Set[String] = {
    Set("buzzer", "electric buzzer", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int):String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + ", which is ")
    if (this.propDevice.get.isActivated) {
      os.append("on")
    } else {
      os.append("off")
    }

    if (mode == MODE_DETAILED) {
      os.append(". ")
      os.append("its anode is connected to: " + this.anode.propElectricalConnection.get.getConnectedToStr() + ". ")
      os.append("its cathode is connected to: " + this.cathode.propElectricalConnection.get.getConnectedToStr() + ". ")
    }

    os.toString
  }

}
