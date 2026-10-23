package scienceworld.processes

import scienceworld.objects.electricalcomponent.ElectricalComponent.VOLTAGE_GENERATOR
import scienceworld.struct.EnvObject
import scienceworld.objects.electricalcomponent.ElectricalComponent._
import scienceworld.objects.electricalcomponent.{PolarizedElectricalComponent, Terminal, UnpolarizedElectricalComponent}



object ElectricalConductivity {


  def unpolarizedElectricalConductivityTick(obj:EnvObject, activateDeviceIfPowered:Boolean = false): Unit = {

    // Only continue if this is an electrical component with unpolarized terminals
    if (!obj.hasUnpolarizedElectricalTerminals()) return

    // Check if this device can be powered/serve as an electrical conductor
    var isPossibleConductor:Boolean = false
    if (obj.isInstanceOf[PolarizedElectricalComponent] || obj.isInstanceOf[UnpolarizedElectricalComponent]) {
      // Electrical components are conductors
      isPossibleConductor = true
    } else if ((obj.propMaterial.isDefined) && (obj.propMaterial.get.electricallyConductive)) {
      // Materials that are electrically conductive are conductors
      //if (obj.name.contains("fork")) println("##### " + obj.name + " IS AN ELECTRICAL CONDUCTOR!")

      isPossibleConductor = true
    }

    // If not a conductor, then clear terminals
    if (!isPossibleConductor) {
      obj.terminal1.get.voltage = None
      obj.terminal2.get.voltage = None
      return
    }

    // If this is an electrical component, check to see if it should be activated
    if (obj.electricalRole == ROLE_VOLTAGE_USER) {
      if (activateDeviceIfPowered) obj.propDevice.get.isActivated = false

      // Check to see if the ground is connected to one side
      // Case 1: Ground is connected to Terminal 1, Voltage is connected to Terminal 2
      if (obj.terminal1.get.connectsToGround() && obj.terminal2.get.connectsToVoltage()) {
        println ("Terminal 1 is ground, Terminal 2 is voltage")
        obj.terminal1.get.voltage = Some(VOLTAGE_GENERATOR)
        if (activateDeviceIfPowered) obj.propDevice.get.isActivated = true
      } else if (obj.terminal2.get.connectsToGround() && obj.terminal1.get.connectsToVoltage()) {
        // Case 2: Ground is connected to Terminal 2, Voltage is connected to Terminal 1
        println ("Terminal 2 is ground, Terminal 1 is voltage")
        obj.terminal2.get.voltage = Some(VOLTAGE_GENERATOR)
        if (activateDeviceIfPowered) obj.propDevice.get.isActivated = true
      }
    }

  }

  /*
   * Check to see if two parts are electrically connected (for goal conditions)
   */

  // Check to see if two parts are electrically connected -- e.g. to test if they're in the same circuit, to meet a goal condition.
  def areComponentsElectricallyConnected(part1:EnvObject, part2:EnvObject): Boolean = {
    if (part1.terminal1.isEmpty) return false
    // Note, here we only go around the circuit one way (via terminal1), assuming that the other check (via terminal2) isn't required if another goal condition is met (e.g. the query object is turned on, signifying the circuit is complete)
    return this.areComponentsElectricallyConnected(part1, part1.terminal1.get, part2)
  }

  def areComponentsElectricallyConnected(part1:EnvObject, part2Name:String): Boolean = {
    var terminal:Option[Terminal] = None
    part1 match {
      case c:PolarizedElectricalComponent => {
        terminal = Some(c.anode)
      }
      case c:EnvObject => {
        terminal = c.terminal1
      }
    }
    if (terminal.isEmpty) return false

    // Note, here we only go around the circuit one way (via terminal1), assuming that the other check (via terminal2) isn't required if another goal condition is met (e.g. the query object is turned on, signifying the circuit is complete)
    return this.areComponentsElectricallyConnected(part1, terminal.get, part2Name)
  }

  private def areComponentsElectricallyConnected(part1:EnvObject, terminalIn:Terminal, part2:EnvObject): Boolean = {
    val otherTerminal = part1.getOtherElectricalTerminal(terminalIn)
    val connections = otherTerminal.get.propElectricalConnection.get.getConnections()

    // Check if directly connected
    for (connection <- connections) {
      // Connections should be to terminals on objects
      connection match {
        case t:Terminal => {
          val parentObject = t.parentObject             // Find the parent object
          if (parentObject == part2) return true        // If it's the same as the object we're looking for, then success
        }
        case _ => { }
      }
    }

    // If not directly connected, recurse
    for (connection <- connections) {
      // Connections should be to terminals on objects
      connection match {
        case t:Terminal => {
          val parentObject = t.parentObject             // Find the parent object
          val otherTerminal = parentObject.getOtherElectricalTerminal(t)
          if (otherTerminal.isDefined) {
            if (this.areComponentsElectricallyConnected(parentObject, otherTerminal.get, part2) == true) return true
          }
        }
        case _ => { }
      }
    }

    // If we've recursed through all connections and no direct or indirect connections have been found, then the objects are not electrically connected
    return false
  }

  private def areComponentsElectricallyConnected(part1:EnvObject, terminalIn:Terminal, part2Name:String, recurseCount:Int = 10): Boolean = {
    if (recurseCount <= 0) return false     // Limit infinite recursion on loop circuits

    val otherTerminal = part1.getOtherElectricalTerminal(terminalIn)
    val connections = otherTerminal.get.propElectricalConnection.get.getConnections()

    // Check if directly connected
    for (connection <- connections) {
      // Connections should be to terminals on objects
      connection match {
        case t:Terminal => {
          val parentObject = t.parentObject             // Find the parent object
          if (parentObject.name == part2Name) return true        // If it's the same as the object we're looking for, then success
        }
        case _ => { }
      }
    }

    // If not directly connected, recurse
    for (connection <- connections) {
      // Connections should be to terminals on objects
      connection match {
        case t:Terminal => {
          val parentObject = t.parentObject             // Find the parent object
          if (this.areComponentsElectricallyConnected(parentObject, t, part2Name, recurseCount-1) == true) return true
        }
        case _ => { }
      }
    }

    // If we've recursed through all connections and no direct or indirect connections have been found, then the objects are not electrically connected
    return false
  }

}
