package scienceworld.objects.electricalcomponent

import scienceworld.objects.electricalcomponent.ElectricalComponent.ROLE_VOLTAGE_USER
import scienceworld.properties.MetalProp
import scienceworld.struct.EnvObject._

/*
 *  Wire
 */

class Wire extends UnpolarizedElectricalComponent {
  this.name = "wire"

  this.propMaterial = Some( new MetalProp() )
  this.electricalRole = ROLE_VOLTAGE_USER


}
