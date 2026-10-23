package scienceworld.objects.electricalcomponent

import scienceworld.objects.electricalcomponent.ElectricalComponent.{ROLE_VOLTAGE_GENERATOR, VOLTAGE_GENERATOR, VOLTAGE_GROUND}
import scienceworld.objects.location.Outside
import scienceworld.properties.{IsActivableDeviceOff, IsActivableDeviceOn, IsNotActivableDeviceOff, IsNotActivableDeviceOn}
import scienceworld.struct.EnvObject
import scienceworld.struct.EnvObject._

import scala.util.control.Breaks.{break, breakable}

/*
 *  Generators
 */

class Generator(val displayOnOff:Boolean = true) extends PolarizedElectricalComponent {
  this.name = "generator"

  this.propDevice = Some(new IsActivableDeviceOn())
  this.electricalRole = ROLE_VOLTAGE_GENERATOR  // Component uses voltage, rather than generating it

  override def tick(): Boolean = {
    // If this generator is activated, then generate a voltage potential at the terminals.
    if (this.propDevice.get.isActivated) {
      this.anode.voltage = Some(VOLTAGE_GENERATOR)
      this.cathode.voltage = Some(VOLTAGE_GROUND)
    } else {
      this.anode.voltage = None
      this.cathode.voltage = None
    }
    super.tick()
  }

  override def getReferents(): Set[String] = {
    Set("generator", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int):String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + "")
    if (displayOnOff) {
      os.append(", which is ")
      if (this.propDevice.get.isActivated) {
        os.append("on")
      } else {
        os.append("off")
      }
    }
    if (mode == MODE_DETAILED) {
      os.append(". ")
      os.append("its anode is connected to: " + this.anode.propElectricalConnection.get.getConnectedToStr() + ". ")
      os.append("its cathode is connected to: " + this.cathode.propElectricalConnection.get.getConnectedToStr() + ". ")
    }

    os.toString
  }

}

class Battery extends Generator(displayOnOff = false) {
  this.name = "battery"

  this.propDevice = Some(new IsNotActivableDeviceOn())      // Always on

}

// Non-renewable
class GasGenerator extends Generator {
  this.name = "gas generator"
  this.propDevice = Some(new IsActivableDeviceOff())
}

class NuclearGenerator extends Generator {
  this.name = "nuclear generator"
  this.propDevice = Some(new IsActivableDeviceOff())
}

// Renewable
// Renewable generator automatically activates when it's outside (i.e. has access to wind/sunlight)
class RenewableOutdoorGenerator extends Generator {
  this.name = "renewable generator"
  this.propDevice = Some(new IsNotActivableDeviceOff())

  override def tick(): Boolean = {
    // If this generator is in an outdoor location, then it is activated.
    breakable {
      var container = this.getContainer()
      val maxCount:Int = 10
      var count:Int = 0

      while (count < maxCount) {
        if (container.isEmpty) {
          this.propDevice.get.isActivated = false               // Generator not in a container -- deactivate
          break()
        } else {
          container.get match {
            case x: Outside => {
              // Is in an outside location -- activate
              this.propDevice.get.isActivated = true            // Generator in an outdoor location -- activate
              break()
            }
            case x: EnvObject => {
              // Check to see if it's a container
              if ((container.get.propContainer.isDefined) && (container.get.propContainer.get.isOpen)) {
                container = container.get.getContainer()        // Generator in an open container (e.g. table) -- recurse.
              } else {
                this.propDevice.get.isActivated = false         // Generator not in an open container -- deactivate
                break()
              }
            }
          }
        }
        count += 1
      }
      // If we reach here, the generator is so deeply nested in containers away from an outdoor location that we'll stop and say it's inaccessible to the things it needs (e.g. wind/solar)
      this.propDevice.get.isActivated = false
    }

    super.tick()
  }

}

// Solar panel -- only works in outdoor environment
class SolarPanel extends RenewableOutdoorGenerator {
  this.name = "solar panel"
  this.propDevice = Some(new IsNotActivableDeviceOff())

}

// Wind generator -- only works in outdoor environment
class WindGenerator extends RenewableOutdoorGenerator {
  this.name = "wind generator"
  this.propDevice = Some(new IsNotActivableDeviceOff())
}
