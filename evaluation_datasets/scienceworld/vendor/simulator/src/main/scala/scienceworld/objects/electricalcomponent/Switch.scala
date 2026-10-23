package scienceworld.objects.electricalcomponent

import scienceworld.objects.electricalcomponent.ElectricalComponent.ROLE_VOLTAGE_SWITCH
import scienceworld.properties.IsActivableDeviceOff
import scienceworld.struct.EnvObject
import scienceworld.struct.EnvObject._

/*
 * Switches
 */
class Switch extends PolarizedElectricalComponent {
  this.name = "switch"
  this.electricalRole = ROLE_VOLTAGE_SWITCH
  this.propDevice = Some( new IsActivableDeviceOff() )


  // Given one terminal, get the other (connected) terminal.
  override def getOtherElectricalTerminal(terminalIn: EnvObject): Option[Terminal] =  {
    // If the switch is deactivated, do not allow any flow
    if (!this.propDevice.get.isActivated) return None

    if (terminalIn == anode) return Some(cathode)
    if (terminalIn == cathode) return Some(anode)

    // Otherwise
    return None
  }


  override def tick():Boolean = {
    super.tick()
  }

  override def getReferents(): Set[String] = {
    Set("component", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + ", which is ")
    if (this.propDevice.get.isActivated) { os.append("on") } else { os.append("off") }
    if (mode == MODE_DETAILED) {
      os.append(". ")
      os.append("its anode is connected to: " + this.anode.propElectricalConnection.get.getConnectedToStr() + ". ")
      os.append("its cathode is connected to: " + this.cathode.propElectricalConnection.get.getConnectedToStr() + ". ")
    }



    os.toString
  }

}
