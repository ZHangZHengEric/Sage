package scienceworld.objects.portal

import scienceworld.properties.{IsContainer, MoveableProperties, PortalProperties}
import scienceworld.struct.EnvObject

import scala.collection.mutable
import scala.collection.mutable.ArrayBuffer


class Portal (val _isOpen:Boolean, val connectsFrom:EnvObject, val connectsTo:EnvObject) extends EnvObject {

  propPortal = Some( new PortalProperties(isOpen=_isOpen, isOpenable=true, connectsFrom=connectsFrom, connectsTo=connectsTo, isLockable = false, isLocked = false) )
  propMoveable = Some( new MoveableProperties(isMovable = false) )

  def getOpenClosedStr():String = {
    if (this.propPortal.get.isOpen == true) return "open"
    return "closed"
  }

  // Check to see if this portal is currently passable
  def isCurrentlyPassable():Boolean = {
    if (this.propPortal.get.isOpen) return true
    // Else
    return false
  }

  // A message that handles all the error cases for why this portal might not be passable.
  def getUnpassableErrorMessage():String = {
    if (isCurrentlyPassable()) return "This " + this.name + " is passable."

    // Check that the door is open
    if (!this.propPortal.get.isOpen) {
      return "The " + this.name + " is not open."
    }
    if (!this.propPortal.get.isLocked) {
      return "The " + this.name + " is locked."
    }
    // Catch all
    return "The " + this.name + " is not currently passable."
  }

  /*
   * Connects from/to
   */

  // Get where the container connects to
  def getConnectsTo(perspectiveContainer:EnvObject):Option[EnvObject] = {
    // Check if we're directly in the containers
    if (perspectiveContainer == connectsFrom) return Some(connectsTo)
    if (perspectiveContainer == connectsTo) return Some(connectsFrom)

    // Otherwise, check containers by recursing down
    if (perspectiveContainer.contains(connectsFrom)) return Some(connectsTo)
    if (perspectiveContainer.contains(connectsTo)) return Some(connectsFrom)

    // Otherwise
    return None
  }

  // Get where the container connects from
  def getConnectsFrom(perspectiveContainer:EnvObject):Option[EnvObject] = {
    // Check if we're directly in the containers
    if (perspectiveContainer == connectsFrom) return Some(connectsFrom)
    if (perspectiveContainer == connectsTo) return Some(connectsTo)

    // Otherwise, check containers by recursing down
    if (perspectiveContainer.contains(connectsFrom)) return Some(connectsFrom)
    if (perspectiveContainer.contains(connectsTo)) return Some(connectsTo)

    // Otherwise
    return None
  }

  // Get both of the points the portal connects
  def getConnectionPoints():Set[EnvObject] = {
    return EnvObject.uuidOrderedSet(Array(connectsFrom, connectsTo))
  }

  // Check if it connects to a given location with a given name
  def doesConnectTo(locationName:String):Boolean = {
    for (connectionPoint <- this.getConnectionPoints()) {
      if (connectionPoint.name.trim.toLowerCase == locationName.trim.toLowerCase) return true
    }
    // Default return
    return false
  }

  /*
   * Referents/description (from perspective of one side of the portal)
   */

  override def getReferents():Set[String] = {
    Set("ERROR: SHOULD USE OVERRIDE FOR PORTAL.")
  }

  def getReferents(perspectiveContainer:EnvObject): Set[String] = {
    val connectsToContainer = this.getConnectsTo(perspectiveContainer)
    if (connectsToContainer.isDefined) {
      return Set(this.name, this.name + " to " + connectsToContainer.get.name, connectsToContainer.get.name + " " + this.name)
    }

    // Catch all
    return Set(this.name, this.name + " from " + connectsFrom.name + " to " + connectsTo.name, this.name + " from " + connectsTo.name + " to " + connectsFrom.name)
  }

  def getCanonicalReferent(perspectiveContainer:EnvObject):String = {
    val connectsToContainer = this.getConnectsTo(perspectiveContainer)
    if (connectsToContainer.isDefined) {
      return this.name + " to " + connectsToContainer.get.name
    }

    return this.name + " from " + connectsFrom.name + " to " + connectsTo.name
  }

  override def getDescriptName(overrideName: String): String = {
    return "door between " + this.connectsFrom.name + " and " + this.connectsTo.name
  }

  override def getDescription(mode: Int): String = {
    return "ERROR: SHOULD USE OVERRIDE FOR PORTAL."
  }

  def getDescription(mode:Int, perspectiveContainer:EnvObject): String = {
    val os = new StringBuilder
    val connectsToContainer = this.getConnectsTo(perspectiveContainer)
    if (connectsToContainer.isDefined) {
      os.append("A " + this.name + " to the " + connectsToContainer.get.name + " (that is ")
      if (this.propPortal.get.isOpen) {
        os.append("open")
      } else {
        os.append("closed")
      }
      os.append(")")

      return os.toString()
    }

    // Catch all
    os.append("A " + this.name + " that connects the " + connectsFrom.name + " to the " + connectsTo.name + " (that is ")
    if (this.propPortal.get.isOpen) {
      os.append("open")
    } else {
      os.append("closed")
    }
    os.append(")")
    return os.toString()
  }

  def getDescriptionSafe(mode:Int, perspectiveContainer:EnvObject):Option[String] = {
    if (this.isHidden()) return None
    return Some(this.getDescription(mode, perspectiveContainer))
  }

}


/*
 * Door (for moving room to room)
 */
class Door(isOpen:Boolean, connectsFrom:EnvObject, connectsTo:EnvObject) extends Portal(isOpen, connectsFrom, connectsTo) {

  def this(connectsFrom:EnvObject, connectsTo:EnvObject) = this(isOpen=false, connectsFrom, connectsTo)

  propPortal = Some( new PortalProperties(isOpen=isOpen, isOpenable=true, connectsFrom=connectsFrom, connectsTo=connectsTo, isLockable = false, isLocked = false) )
  propMoveable = Some( new MoveableProperties(isMovable = false) )

  this.name = "door"

}


/*
 * Drain (for liquids)
 */
class LiquidDrain(isOpen:Boolean, connectsFrom:EnvObject, connectsTo:EnvObject) extends Portal(isOpen, connectsFrom, connectsTo) {

  def this(connectsFrom:EnvObject, connectsTo:EnvObject) = this(isOpen=false, connectsFrom, connectsTo)

  propPortal = Some( new PortalProperties(isOpen=isOpen, isOpenable=true, connectsFrom=connectsFrom, connectsTo=connectsTo, isLockable = false, isLocked = false) )
  propMoveable = Some( new MoveableProperties(isMovable = false) )

  this.name = "drain"

  /*
   * Tick
   */
  override def tick(): Boolean = {
    // If there are any liquids in the 'from' container, move them through the drain.
    val objsToMove = new ArrayBuffer[EnvObject]()
    //println ("#### DRAIN TICK!!!")

    if (propPortal.get.isOpen) {

      // Find all liquids
      for (containedObj <- connectsFrom.getContainedObjects()) {
        if (containedObj.propMaterial.isDefined) {
          if (containedObj.propMaterial.get.stateOfMatter == "liquid") {
            objsToMove.append(containedObj)
          }
        }
      }

      // Move all liquids through drain to the 'to' container
      for (liquidObj <- objsToMove) {
        //println ("LiquidDrain: Moving " + liquidObj.name + " from " + liquidObj.getContainer().get.name + " to " + connectsTo.name + ". ")
        connectsTo.addObject(liquidObj)
      }

    }

    super.tick()
  }


  /*
   * Referents/Descriptions
   */

  override def getReferents(perspectiveContainer:EnvObject): Set[String] = {
    val drainContainer = this.getConnectsFrom(perspectiveContainer)
    if (drainContainer.isDefined) {
      return Set(this.name, drainContainer.get.name + " " + this.name)
    }

    // Catch all
    return Set(this.name)
  }

  override def getDescription(mode:Int, perspectiveContainer:EnvObject): String = {
    val os = new StringBuilder

    os.append ("A " + this.name + ", which is " + this.getOpenClosedStr())

    return os.toString()
  }

}
