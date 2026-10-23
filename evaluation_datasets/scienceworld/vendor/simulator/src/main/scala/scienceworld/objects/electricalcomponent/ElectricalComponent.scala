package scienceworld.objects.electricalcomponent

import scienceworld.objects.electricalcomponent.ElectricalComponent.{ROLE_VOLTAGE_GENERATOR, ROLE_VOLTAGE_SWITCH, ROLE_VOLTAGE_USER, VOLTAGE_GENERATOR, VOLTAGE_GROUND}
import scienceworld.processes.ElectricalConductivity
import scienceworld.properties.{ElectricalConnectionProperties, IsActivableDeviceOff, IsActivableDeviceOn, IsNotActivableDeviceOff, IsNotActivableDeviceOn, MoveableProperties}
import scienceworld.struct.EnvObject
import scienceworld.struct.EnvObject._

class PolarizedElectricalComponent() extends EnvObject(name = "", objType = "", includeElectricalTerminals = false) {
  this.name = "component"

  this.propDevice = Some(new IsNotActivableDeviceOff())                       // By default, not activable, and is off
  this.propMoveable = Some( new MoveableProperties(isMovable = true) )        // Moveable

  // Each electrical component has an anode and a cathode
  val anode = new Anode(this)
  val cathode = new Cathode(this)
  this.addObject(anode)
  this.addObject(cathode)

  // Electrical role (generator, or consumer)
  electricalRole = ROLE_VOLTAGE_USER


  override def isElectricallyConnected():Boolean = {
    if (anode.propElectricalConnection.get.size() > 0) return true
    if (cathode.propElectricalConnection.get.size() > 0) return true
    return false
  }

  // Given one terminal, get the other (connected) terminal.
  override def getOtherElectricalTerminal(terminalIn:EnvObject):Option[Terminal] = {
    if (terminalIn == anode) return Some(cathode)
    if (terminalIn == cathode) return Some(anode)

    // Otherwise
    return None
  }

  override def disconnectElectricalTerminals() {
    this.anode.disconnect()
    this.cathode.disconnect()
  }

  override def tick():Boolean = {
    //println ("TICK: " + this.name)

    // If this is an electrical component, check to see if it should be activated
    if (electricalRole == ROLE_VOLTAGE_USER) {
      this.propDevice.get.isActivated = false

      // Check to see if the ground is connected
      if (this.anode.connectsToGround() && this.cathode.connectsToVoltage()) {
        // Ground is connected, voltage is connected
        this.anode.voltage = Some(VOLTAGE_GENERATOR)
        this.propDevice.get.isActivated = true
      }
    }

    super.tick()
  }

  override def getReferents(): Set[String] = {
    Set("component", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + ". ")
    if (mode == MODE_DETAILED) {
      os.append("its anode is connected to: " + this.anode.propElectricalConnection.get.getConnectedToStr() + ". ")
      os.append("its cathode is connected to: " + this.cathode.propElectricalConnection.get.getConnectedToStr() + ". ")
    }

    //if (this.propDevice.get.isActivated) { os.append("on") } else { os.append("off") }

    os.toString
  }

}


class UnpolarizedElectricalComponent extends EnvObject {
  this.name = "component"

  this.propDevice = Some(new IsNotActivableDeviceOff())                       // By default, not activable, and is off
  this.propMoveable = Some( new MoveableProperties(isMovable = true) )        // Moveable

  // Electrical role (generator, or consumer)
  electricalRole = ROLE_VOLTAGE_USER

  // Terminals on normal objects are 'faux'/hidden, but are not hidden on actual electrical components
  terminal1.get.setHidden(false)
  terminal2.get.setHidden(false)


  override def tick():Boolean = {
    //println ("TICK: " + this.name)

    // Electrical conductivity: Potentially conduct electricity, if an electrical conductor and connected to other conductors
    ElectricalConductivity.unpolarizedElectricalConductivityTick(this, activateDeviceIfPowered = true)

    super.tick()
  }

  override def getReferents(): Set[String] = {
    Set("component", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName())
    if (mode == MODE_DETAILED) {
      os.append("its terminal 1 is connected to: " + this.terminal1.get.propElectricalConnection.get.getConnectedToStr() + ". ")
      os.append("its terminal 2 is connected to: " + this.terminal2.get.propElectricalConnection.get.getConnectedToStr() + ". ")
    }

    //if (this.propDevice.get.isActivated) { os.append("on") } else { os.append("off") }

    os.toString
  }

}


object ElectricalComponent {
  val ROLE_VOLTAGE_GENERATOR    =   1
  val ROLE_VOLTAGE_USER         =   2
  val ROLE_VOLTAGE_SWITCH       =   3

  val VOLTAGE_GROUND            =   0.0
  val VOLTAGE_GENERATOR         =   9.0

}




/*
 * Terminal
 */
class Terminal(val parentObject:EnvObject, _name:String = "terminal") extends EnvObject(name = "", objType = "", includeElectricalTerminals = false) {
  this.name = _name

  propMoveable = Some( new MoveableProperties(isMovable = false) )                        // Not moveable
  propElectricalConnection = Some( new ElectricalConnectionProperties() )                 // Electrical connection point

  var voltage:Option[Double] = None

  // Remove all electrical connections to this terminal
  def disconnect(): Unit = {
    val connections = propElectricalConnection.get.getConnections()

    // Remove these connections from this object to other objects
    for (obj <- connections) {
      propElectricalConnection.get.removeConnection(obj)
    }

    // Remove the reciprocal connections from that object to this object
    for (obj <- connections) {
      if (obj.propElectricalConnection.isDefined) {
        obj.propElectricalConnection.get.removeConnection(this)
      }
    }
  }

  // Does this terminal connect to a voltage source?
  def connectsToVoltage():Boolean = {
    // For each connected object
    for (obj <- propElectricalConnection.get.getConnections()) {
      obj match {
        case co:Terminal => {
          if ((co.voltage.isDefined) && (co.voltage.get == VOLTAGE_GENERATOR)) return true
        }
        case _ => {
          println("#### OTHER")
        }
      }
    }

    return false
  }


  // Check to see if this terminal (ultimately) connects to ground
  def connectsToGround(maxSteps:Int = 10):Boolean = {
    //println(" * connectsToGround(" + this.name + " / " + this.parentObject.name + " / " + maxSteps + "):")

    // For each connected object
    for (obj <- propElectricalConnection.get.getConnections()) {
      //println ("\tconnected to object: " + obj.toStringMinimal() + " on " + obj.getContainer().get.name)
      obj match {
        case co:Terminal => {
          val parentObject = co.parentObject
          //println ("\t\tparent object: " + parentObject.toStringMinimal())
          parentObject match {
            case po:PolarizedElectricalComponent => {
              //println("\t\tPolarized")
              // Step 1: Find the parent object to see if it's a generator, and if this is connected to ground (if so, return true)
              if (po.isInstanceOf[Generator]) {
                //println ("\t\tAppears to be connected to a generator: " + co.name + " " + co.voltage)
                if ((co.voltage.isDefined) && (co.voltage.get == VOLTAGE_GROUND)) {
                  // Connected to ground
                  //println("true1")
                  return true
                } else {
                  // Not connected to ground -- and, stop traversal through the battery
                  //println("false1")
                  return false
                }
              }

              // Step 2: If the parent object isn't a generator, traverse through the object, IF the two terminals are "connected" (i.e. a light bulb, a switch that's open, etc).
              val otherTerminal = po.getOtherElectricalTerminal(co)
              if (otherTerminal.isEmpty) {
                //println("false2")
                return false
              }         // Other terminal doesn't exist or is not connected in a switch, return false
              // Other terminal exists, traverse/recurse
              if ( maxSteps > 0 && otherTerminal.get.connectsToGround(maxSteps-1) == true) {
                //println("true2")
                return true
              }      // If the recursive case returns true, then that pin connects to ground.  If it doesn't, continue on other connections.

            }

            case unpo:UnpolarizedElectricalComponent => {
              //println("\t\tUnpolarized")
              // Step 1: Unpolarized can't be a generator, so skip this check.

              // Step 2: If the parent object isn't a generator, traverse through the object, IF the two terminals are "connected" (i.e. a light bulb, a switch that's open, etc).
              val otherTerminal = unpo.getOtherElectricalTerminal(co)
              if (otherTerminal.isEmpty) {
                //println("false2")
                return false
              }         // Other terminal doesn't exist or is not connected in a switch, return false
              // Other terminal exists, traverse/recurse
              if ( maxSteps > 0 && otherTerminal.get.connectsToGround(maxSteps-1) == true) {
                //println("true2")
                return true
              }      // If the recursive case returns true, then that pin connects to ground.  If it doesn't, continue on other connections.

            }

            case envobj:EnvObject => {
              // Step 0: If the object is made of a non-conductive material, then return
              if ((envobj.propMaterial.isEmpty) || (!envobj.propMaterial.get.electricallyConductive)) {
                return false
              }

              // Step 1: Non-electrical object can't be a generator, so skip this check.

              // Step 2: If the parent object isn't a generator, traverse through the object, IF the two terminals are "connected" (i.e. a light bulb, a switch that's open, etc).
              val otherTerminal = envobj.getOtherElectricalTerminal(co)
              if (otherTerminal.isEmpty) {
                //println("false2")
                return false
              }         // Other terminal doesn't exist or is not connected in a switch, return false
              // Other terminal exists, traverse/recurse
              if ( maxSteps > 0 && otherTerminal.get.connectsToGround(maxSteps-1) == true) {
                //println("true2")
                return true
              }      // If the recursive case returns true, then that pin connects to ground.  If it doesn't, continue on other connections.
            }

            case _ => {
              // Other non-electrical component object
              println("### CONNECTED TO UNRECOGNIZED ELECTRICAL COMPONENT")
              println("### Parent Object (1): " + parentObject.toStringMinimal())
            }
          }


        }

        case _ => {
          // Other object
          println("### CONNECTED TO UNRECOGNIZED ELECTRICAL COMPONENT")
          println("### Parent Object (2): " + obj.toStringMinimal())
        }
      }

    }

    //println("false (default)")
    false
  }

  override def tick():Boolean = {

    super.tick()
  }

  override def getReferents():Set[String] = {
    Set("terminal", this.name, this.name + " on " + parentObject.name, parentObject.name + " " + this.name, this.getDescriptName(), this.getDescriptName() + " on " + parentObject.name)
  }

  override def getDescription(mode: Int): String = {
    if (mode == MODE_CURSORY_DETAIL) {
      return "a " + this.getDescriptName() + " on " + parentObject.name
    } else if (mode == MODE_DETAILED) {
      return "a " + this.getDescriptName() + ".  it is connected to: " + this.propElectricalConnection.get.getConnectedToStr() + ". "
    }

    // Default return
    return "a " + this.getDescriptName() + " on " + parentObject.name
  }
}

/*
 * Anode
 */
class Anode(parentObject:EnvObject) extends Terminal(parentObject) {
  this.name = "anode"

}

/*
 * Cathode
 */
class Cathode(parentObject:EnvObject) extends Terminal(parentObject) {
  this.name = "cathode"

}
