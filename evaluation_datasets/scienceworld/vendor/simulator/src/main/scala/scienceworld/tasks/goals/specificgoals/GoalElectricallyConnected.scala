package scienceworld.tasks.goals.specificgoals

import scienceworld.objects.agent.Agent
import scienceworld.objects.electricalcomponent.{Battery, Generator, LightBulb, PolarizedElectricalComponent, Terminal, Wire}
import scienceworld.processes.ElectricalConductivity
import scienceworld.struct.EnvObject
import scienceworld.tasks.goals.{Goal, GoalReturn, GoalSequence}

import scala.util.control.Breaks.{break, breakable}

class GoalElectricallyConnected(connectedPartName:String = "", failIfWrong:Boolean = true, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    println ("GOAL CHECKING:")

    // Check for a focus object
    if (obj.isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Check that the focus object of this step is the same as the focus object of the previous step
    if (gs.getLastSatisfiedObject().isDefined) {
      if (gs.getLastSatisfiedObject().get != obj.get) return GoalReturn.mkSubgoalUnsuccessful()
    }

    // Check that the focus object is electrically connected to an object with 'connectedPartName'
    if (ElectricalConductivity.areComponentsElectricallyConnected(obj.get, connectedPartName)) {
      this.satisfiedWithObject = obj
      return GoalReturn.mkSubgoalSuccess()
    } else {
      // Case: The focus object is not electrically connected to an object named 'connectedPartName'
      if (failIfWrong) {
        // Return: Task failure
        return GoalReturn.mkTaskFailure()
      } else {
        // Return: Subgoal not passed
        return GoalReturn.mkSubgoalUnsuccessful()
      }
    }

  }

}


// Returns true if there is at least one object with 'objectName' that is connected to a Wire through whichever terminals are specified as true (terminal1, terminal2, anode, cathode)
class GoalObjectConnectedToWire(objectName:String, val terminal1:Boolean = true, val terminal2:Boolean = true, val anode:Boolean = true, val cathode:Boolean = true, _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // NOTE: Focus object not required

    // If agent is not in a container, do not continue evaluation
    if (agent.getContainer().isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Get agent location
    val agentLocation = agent.getContainer().get
    val visibleObjects = agentLocation.getContainedObjectsAndPortalsRecursive(includeHidden = false, includePortalConnections = false)

    var found:Boolean = false
    breakable {
      for (vObj <- visibleObjects) {
        if ((vObj.name.toLowerCase == objectName.toLowerCase) || (vObj.getDescriptName().toLowerCase == objectName.toLowerCase)) {

          vObj match {
            case polObj:PolarizedElectricalComponent => {
              // Check that the Anode is connected to a wire
              if (anode) {
                val connections = polObj.anode.propElectricalConnection.get.getConnections()
                for (cObj <- connections) {
                  cObj match {
                    case term:Terminal => {
                      term.parentObject match {
                        case _:Wire => {
                          found = true
                          break()
                        }
                        case _ => { } // do nothing
                      }
                    }
                    case _ => { } // do nothing
                  }
                }
              }

              // Check that the Cathode is connected to a wire
              if (cathode) {
                val connections = polObj.cathode.propElectricalConnection.get.getConnections()
                for (cObj <- connections) {
                  cObj match {
                    case term:Terminal => {
                      term.parentObject match {
                        case _:Wire => {
                          found = true
                          break()
                        }
                        case _ => { } // do nothing
                      }
                    }
                    case _ => { } // do nothing
                  }
                }
              }

            }
            case unpolObj:EnvObject => {
              // Check that Terminal 1 is connected to a wire
              if ((terminal1) && (unpolObj.terminal1.isDefined)) {
                val connections = unpolObj.terminal1.get.propElectricalConnection.get.getConnections()
                for (cObj <- connections) {
                  cObj match {
                    case term:Terminal => {
                      term.parentObject match {
                        case _:Wire => {
                          found = true
                          break()
                        }
                        case _ => { } // do nothing
                      }
                    }
                    case _ => { } // do nothing
                  }
                }
              }

              // Check that Terminal 2 is connected to a wire
              if ((terminal2) && (unpolObj.terminal2.isDefined)) {
                val connections = unpolObj.terminal2.get.propElectricalConnection.get.getConnections()
                for (cObj <- connections) {
                  cObj match {
                    case term:Terminal => {
                      term.parentObject match {
                        case _:Wire => {
                          found = true
                          break()
                        }
                        case _ => { } // do nothing
                      }
                    }
                    case _ => { } // do nothing
                  }
                }
              }

            }
          }

        }
      }
    }

    // First initialization: Keep track of starting location
    if (found) {
      return GoalReturn.mkSubgoalSuccess()
    }

    // Otherwise
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}


// Returns true if there is at least one object with 'objectName' that is connected to a Wire through whichever terminals are specified as true (terminal1, terminal2, anode, cathode)
class GoalWireConnectsObjectAndAnyPowerSource(objectName:String, powerSourceName:String = "", _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // NOTE: Focus object not required

    // If agent is not in a container, do not continue evaluation
    if (agent.getContainer().isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Get agent location
    val agentLocation = agent.getContainer().get
    val visibleObjects = agentLocation.getContainedObjectsAndPortalsRecursive(includeHidden = false, includePortalConnections = false)

    var found:Boolean = false
    breakable {
      for (vObj <- visibleObjects) {
        vObj match {
          case wire:Wire => {
            // println ("Found wire: " + wire.toStringMinimal())
            var foundObject:Boolean = false
            var foundPowerSource:Boolean = false

            // Wire 1
            if (wire.terminal1.isDefined) {
              val connectedTo = wire.terminal1.get.propElectricalConnection.get.getConnections()
              for (cObj_ <- connectedTo) {
                cObj_ match {
                  case cObj:Terminal => {
                    val pObj = cObj.parentObject
                    // Check for a connection to the object
                    if ((pObj.name.toLowerCase == objectName.toLowerCase) || (pObj.getDescriptName().toLowerCase == objectName.toLowerCase)) foundObject = true
                    // Check for a connection to a power source
                    pObj match {
                      case ps: Generator => {
                        if ((powerSourceName == "") || (ps.name.toLowerCase == powerSourceName.toLowerCase) || (ps.getDescriptName().toLowerCase == powerSourceName.toLowerCase)) {
                          foundPowerSource = true
                        }
                      }
                      case _ => {} // do nothing
                    }
                  }
                  case _ => { } // do nothing
                }
              }
            }

            // Wire 2
            if (wire.terminal2.isDefined) {
              val connectedTo = wire.terminal2.get.propElectricalConnection.get.getConnections()
              for (cObj_ <- connectedTo) {
                cObj_ match {
                  case cObj:Terminal => {
                    val pObj = cObj.parentObject
                    // Check for a connection to the object
                    if ((pObj.name.toLowerCase == objectName.toLowerCase) || (pObj.getDescriptName().toLowerCase == objectName.toLowerCase)) foundObject = true
                    // Check for a connection to a power source
                    pObj match {
                      case ps: Generator => {
                        if ((powerSourceName == "") || (ps.name.toLowerCase == powerSourceName.toLowerCase) || (ps.getDescriptName().toLowerCase == powerSourceName.toLowerCase)) {
                          foundPowerSource = true
                        }
                      }
                      case _ => {} // do nothing
                    }
                  }
                  case _ => { } // do nothing
                }
              }
            }

            if ((foundObject) && (foundPowerSource)) {
              found = true
              break()
            }
          }
          case _ => { }   // do nothing
        }

      }
    }

    // First initialization: Keep track of starting location
    if (found) {
      return GoalReturn.mkSubgoalSuccess()
    }

    // Otherwise
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}

// Returns true if there is at least one object with 'objectName' that is connected to a Wire through whichever terminals are specified as true (terminal1, terminal2, anode, cathode)
class GoalWireConnectsObjectAndAnyLightBulb(objectName:String, lightBulbName:String = "", _isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // NOTE: Focus object not required

    // If agent is not in a container, do not continue evaluation
    if (agent.getContainer().isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Get agent location
    val agentLocation = agent.getContainer().get
    val visibleObjects = agentLocation.getContainedObjectsAndPortalsRecursive(includeHidden = false, includePortalConnections = false)

    var found:Boolean = false
    breakable {
      for (vObj <- visibleObjects) {
        vObj match {
          case wire:Wire => {
            // println ("Found wire: " + wire.toStringMinimal())
            var foundObject:Boolean = false
            var foundLightBulb:Boolean = false

            // Wire 1
            if (wire.terminal1.isDefined) {
              val connectedTo = wire.terminal1.get.propElectricalConnection.get.getConnections()
              for (cObj_ <- connectedTo) {
                cObj_ match {
                  case cObj:Terminal => {
                    val pObj = cObj.parentObject
                    // Check for a connection to the object
                    if ((pObj.name.toLowerCase == objectName.toLowerCase) || (pObj.getDescriptName().toLowerCase == objectName.toLowerCase)) foundObject = true
                    // Check for a connection to a light bulb
                    pObj match {
                      case lb: LightBulb => {
                        if ((lightBulbName == "") || (lb.name.toLowerCase == lightBulbName.toLowerCase) || (lb.getDescriptName().toLowerCase == lightBulbName.toLowerCase)) {
                          foundLightBulb = true
                        }
                      }
                      case _ => {} // do nothing
                    }
                  }
                  case _ => { } // do nothing
                }
              }
            }

            // Wire 2
            if (wire.terminal2.isDefined) {
              val connectedTo = wire.terminal2.get.propElectricalConnection.get.getConnections()
              for (cObj_ <- connectedTo) {
                cObj_ match {
                  case cObj:Terminal => {
                    val pObj = cObj.parentObject
                    // Check for a connection to the object
                    if ((pObj.name.toLowerCase == objectName.toLowerCase) || (pObj.getDescriptName().toLowerCase == objectName.toLowerCase)) foundObject = true
                    // Check for a connection to a light bulb
                    pObj match {
                      case lb: LightBulb => {
                        if ((lightBulbName == "") || (lb.name.toLowerCase == lightBulbName.toLowerCase) || (lb.getDescriptName().toLowerCase == lightBulbName.toLowerCase)) {
                          foundLightBulb = true
                        }
                      }
                      case _ => {} // do nothing
                    }
                  }
                  case _ => { } // do nothing
                }
              }
            }

            if ((foundObject) && (foundLightBulb)) {
              found = true
              break()
            }
          }
          case _ => { }   // do nothing
        }

      }
    }

    // First initialization: Keep track of starting location
    if (found) {
      return GoalReturn.mkSubgoalSuccess()
    }

    // Otherwise
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}

// Returns true if there is at least one object with 'objectName' that is connected to a Wire through whichever terminals are specified as true (terminal1, terminal2, anode, cathode)
class GoalWireConnectsPowerSourceAndAnyLightBulb(_isOptional:Boolean = false, description:String = "", key:String = "", keysMustBeCompletedBefore:Array[String] = Array.empty[String]) extends Goal(description, key, keysMustBeCompletedBefore) {
  this.isOptional = _isOptional

  override def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    // NOTE: Focus object not required

    // If agent is not in a container, do not continue evaluation
    if (agent.getContainer().isEmpty) return GoalReturn.mkSubgoalUnsuccessful()

    // Get agent location
    val agentLocation = agent.getContainer().get
    val visibleObjects = agentLocation.getContainedObjectsAndPortalsRecursive(includeHidden = false, includePortalConnections = false)

    var found:Boolean = false
    breakable {
      for (vObj <- visibleObjects) {
        vObj match {
          case wire:Wire => {
            // println ("Found wire: " + wire.toStringMinimal())
            var foundPowerSource:Boolean = false
            var foundLightBulb:Boolean = false

            // Wire 1
            if (wire.terminal1.isDefined) {
              val connectedTo = wire.terminal1.get.propElectricalConnection.get.getConnections()
              for (cObj_ <- connectedTo) {
                cObj_ match {
                  case cObj:Terminal => {
                    val pObj = cObj.parentObject
                    // Check for a connection to a power source
                    pObj match {
                      case ps: Generator => {
                        foundPowerSource = true
                      }
                      case _ => {} // do nothing
                    }
                    // Check for a connection to a light bulb
                    pObj match {
                      case lb: LightBulb => {
                        foundLightBulb = true
                      }
                      case _ => {} // do nothing
                    }
                  }
                  case _ => { } // do nothing
                }
              }
            }

            // Wire 2
            if (wire.terminal2.isDefined) {
              val connectedTo = wire.terminal2.get.propElectricalConnection.get.getConnections()
              for (cObj_ <- connectedTo) {
                cObj_ match {
                  case cObj:Terminal => {
                    val pObj = cObj.parentObject
                    // Check for a connection to a power source
                    pObj match {
                      case ps: Generator => {
                        foundPowerSource = true
                      }
                      case _ => {} // do nothing
                    }
                    // Check for a connection to a light bulb
                    pObj match {
                      case lb: LightBulb => {
                        foundLightBulb = true
                      }
                      case _ => {} // do nothing
                    }
                  }
                  case _ => { } // do nothing
                }
              }
            }

            if ((foundPowerSource) && (foundLightBulb)) {
              found = true
              break()
            }
          }
          case _ => { }   // do nothing
        }

      }
    }

    // First initialization: Keep track of starting location
    if (found) {
      return GoalReturn.mkSubgoalSuccess()
    }

    // Otherwise
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}
