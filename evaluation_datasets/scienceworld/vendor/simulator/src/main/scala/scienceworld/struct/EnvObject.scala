package scienceworld.struct

import scienceworld.objects.portal.Portal
import scienceworld.properties.{ContainerProperties, CoolingSourceProperties, DeviceProperties, EdibilityProperties, ElectricalConnectionProperties, HeatSourceProperties, LifeProperties, MaterialProperties, MoveableProperties, PollinationProperties, PortalProperties}
import scienceworld.processes.{Combustion, ElectricalConductivity, HeatTransfer, StateOfMatter}
import util.{UniqueIdentifier, UniqueTypeID}

import scala.collection.mutable
import scala.collection.mutable.ArrayBuffer
import EnvObject._
import scienceworld.objects.electricalcomponent.ElectricalComponent.ROLE_VOLTAGE_USER
import scienceworld.objects.electricalcomponent.{PolarizedElectricalComponent, Terminal, UnpolarizedElectricalComponent}
import scienceworld.processes.genetics.ChromosomePair

import scala.reflect.ClassTag


class EnvObject(var name:String, var objType:String, includeElectricalTerminals:Boolean = true) {

  // Alternate constructors
  def this() = this(name = "", objType = "")

  // Variable noting whether this object has been deleted (removed from the simulation)
  var deleted:Boolean = false

  // Contained objects
  private val containedObjects = mutable.Set[EnvObject]()
  private var inContainer:Option[EnvObject] = None

  // Portals
  private val portals = mutable.Set[Portal]()

  // Is this object visible, or a faux/hidden object?
  private var _isHidden:Boolean = false

  // Has this object been processed this tick?
  var tickCompleted:Boolean = false

  // Each (potentially) electrical component has two terminals
  val terminal1:Option[Terminal] = if (includeElectricalTerminals) { Some( new Terminal(this, "terminal 1") ) } else { None }
  val terminal2:Option[Terminal] = if (includeElectricalTerminals) { Some( new Terminal(this, "terminal 2") ) } else { None }
  if (includeElectricalTerminals) {
    // Terminals on normal objects are 'faux'/hidden
    terminal1.get.setHidden(true)
    terminal2.get.setHidden(true)

    this.addObject(terminal1.get)
    this.addObject(terminal2.get)
  }
  // Electrical role (generator, or consumer)
  var electricalRole = ROLE_VOLTAGE_USER


  // Unique identifier
  val uuid = UniqueIdentifier.getNextID()

  // Properties
  var propMaterial:Option[MaterialProperties] = None
  var propEdibility:Option[EdibilityProperties] = None
  var propContainer:Option[ContainerProperties] = None
  var propDevice:Option[DeviceProperties] = None
  var propHeatSource:Option[HeatSourceProperties] = None
  var propCoolingSource:Option[CoolingSourceProperties] = None
  var propPortal:Option[PortalProperties] = None
  var propMoveable:Option[MoveableProperties] = Some( new MoveableProperties(isMovable = true) )
  var propElectricalConnection:Option[ElectricalConnectionProperties] = None
  var propLife:Option[LifeProperties] = None
  var propChromosomePairs:Option[ChromosomePair] = None
  var propPollination:Option[PollinationProperties] = None

  /*
   * Typing
   */
  val className = this.getClass().getCanonicalName()
  val typeID:Long = UniqueTypeID.getID(className)


  /*
   * Portals
   */
  def addPortal(portalIn:Portal): Unit = {
    this.portals.add(portalIn)
  }

  def removePortal(portalIn:Portal):Boolean = {
    if (!this.portals.contains(portalIn)) return false
    this.portals.remove(portalIn)
  }

  def getPortals(includeHidden:Boolean = true):Set[Portal] = {
    if (includeHidden) {
      return uuidOrderedSet(this.portals)
    } else {
      val out = mutable.Set[Portal]()
      for (p <- this.portals) {
        if (!p.isHidden()) out.add(p)
      }
      return uuidOrderedSet(out)
    }
  }

  // Get both portals and objects
  def getContainedObjectsAndPortals(includeHidden:Boolean = true):Set[EnvObject] = {
    if (includeHidden) {
      return uuidOrderedSet(this.containedObjects ++ this.portals)
    } else {
      uuidOrderedSet(this.getContainedObjectsNotHidden() ++ this.getPortals())
    }

  }


  def getContainedObjectsAndPortalsRecursive(includeHidden:Boolean = false, includePortalConnections:Boolean = false):Set[EnvObject] = {
    var out = mutable.Set[EnvObject]()

    val thisObjects = this.getContainedObjects()
    val thisPortals = this.getPortals()
    var portalConnections = Set[EnvObject]()

    // Add local objects
    for (obj <- thisObjects) {
      if (!obj.isHidden() || (includeHidden == true)) out.add(obj)
    }
    for (obj <- thisPortals) {
      if (!obj.isHidden() || (includeHidden == true)) {
        out.add(obj)
        if (includePortalConnections) {
          portalConnections = portalConnections ++ obj.getConnectionPoints()
          //println("Portal connections: " + portalConnections.map(_.toStringMinimal()).mkString(", "))
        }
      }
    }

    // Recurse
    for (obj <- thisObjects) {
      if (!obj.isHidden() || (includeHidden == true)) {
        out = out ++ obj.getContainedObjectsAndPortalsRecursive(includeHidden, includePortalConnections)
      }
    }

    out = out ++ portalConnections

    // Return
    uuidOrderedSet(out)
  }

  /*
   * Object containment
   */

  def getContainer():Option[EnvObject] = this.inContainer

  def getContainedObjects(includeHidden:Boolean = true):Set[EnvObject] = {
    if (includeHidden) return uuidOrderedSet(this.containedObjects)
    return uuidOrderedSet(this.containedObjects.filter(!_.isHidden()))
  }

  def getContainedObjectsRecursive():Set[EnvObject] = {
    var out = mutable.Set[EnvObject]()
    // Add objects contained in this object
    out ++= this.getContainedObjects()
    // Recurse
    for (obj <- this.getContainedObjects()) {
      out ++= obj.getContainedObjectsRecursive()
    }

    // Return
    uuidOrderedSet(out)
  }

  // Get a list of objects easily accessible from this level (i.e. contained in this object, OR in an open container contained in this object)
  def getContainedObjectsRecursiveAccessible(includeHidden:Boolean = false):Set[EnvObject] = {
    var out = mutable.Set[EnvObject]()
    // Add objects contained in this object
    out ++= this.getContainedObjects(includeHidden)
    // Recurse
    for (obj <- this.getContainedObjects(includeHidden)) {
      // Only recurse into open containers
      if ((obj.propContainer.isDefined) && (obj.propContainer.get.isOpen)) {
        out ++= obj.getContainedObjectsRecursiveAccessible(includeHidden)
      }
    }

    // Return
    uuidOrderedSet(out)
  }

  def getContainedObjectsNotHidden():Set[EnvObject] = {
    uuidOrderedSet(this.containedObjects.filter(_.isHidden() == false))
  }

  def getContainedAccessibleObjects(includeHidden:Boolean = false, includePortals:Boolean = true):Set[EnvObject] = {
    var out = mutable.Set[EnvObject]()
    // Contained objects in this container
    for (cObj <- this.getContainedObjects()) {
      if (!cObj.isHidden() || (includeHidden == true)) {   // If object is not hidden
        out.add(cObj)           // Add it

        //## Add an object's electrical terminals, if applicable
        cObj match {
          case polObj:PolarizedElectricalComponent => {
            out.add(polObj.anode)
            out.add(polObj.cathode)
          }
          case unpolObj:UnpolarizedElectricalComponent => {
            if (unpolObj.terminal1.isDefined) out.add(unpolObj.terminal1.get)
            if (unpolObj.terminal2.isDefined) out.add(unpolObj.terminal2.get)
          }
          case _:EnvObject => {
            if (includeHidden) {
              if (cObj.terminal1.isDefined) out.add(cObj.terminal1.get)
              if (cObj.terminal2.isDefined) out.add(cObj.terminal2.get)
            }
          }
        }

        if ((cObj.propContainer.isDefined) && (cObj.propContainer.get.isOpen)) {      // If the object is an open container, add it's contents
          out ++= cObj.getContainedAccessibleObjects(includeHidden, includePortals)
        }
      }
    }
    // Also add portals?
    if (includePortals) {
      for (pObj <- this.getPortals()) {
        if (pObj.isHidden() || (includeHidden == true)) {
          out.add(pObj)
        }
      }
    }

    // Return
    uuidOrderedSet(out)
  }

  def getContainedObjectsOfType[T:ClassTag]():Set[EnvObject] = {
    val out = mutable.Set[EnvObject]()
    for (obj <- this.containedObjects) {
      obj match {
        case x:T => out.add(obj)
        case _ => {}
      }
    }
    return uuidOrderedSet(out)
  }

  def getContainedAccessibleObjectsOfType[T:ClassTag](includeHidden:Boolean = false, includePortals:Boolean = true):Set[EnvObject] = {
    val out = mutable.Set[EnvObject]()
    for (obj <- this.getContainedAccessibleObjects(includeHidden, includePortals)) {
      obj match {
        case x:T => out.add(obj)
        case _ => {}
      }
    }
    return uuidOrderedSet(out)
  }


  // Add an object to this container
  def addObject(objIn:EnvObject): Unit = {
    if (objIn == this) return // throw new RuntimeException("ERROR: addObject(): Attempted to add self to container (" + this.name + ").")

    objIn.removeAndResetContainer()    // Remove from it's previous container
    this.containedObjects.add(objIn)
    objIn.inContainer = Some(this)
  }

  // Remove an object from this container
  def removeObjectFromContainer(objIn:EnvObject):Boolean = {
    // Check that object is contained in this container -- if not, return an error
    if (!containedObjects.contains(objIn)) return false

    // If we reach here, the object is contained in this container.
    containedObjects.remove(objIn)    // Remove from this container
    objIn.removeAndResetContainer()            // Update the object's back reference to show that it has no container
    return true
  }

  // Removes *this* object from it's container
  def removeAndResetContainer(): Unit = {
    // If this object is in some container, remove it from the container
    if (this.inContainer.isDefined) {
      this.inContainer.get.removeObjectFromContainer(this)
    }
    // Update this object's back reference to show that it has no container
    this.inContainer = None
  }

  // Moves all contained objects out of this container
  def moveAllContainedObjects(newContainer:EnvObject): Unit = {
    for (cObj <- this.getContainedObjects()) {
      newContainer.addObject(cObj)
    }
  }

  // Check to see if an object is in this container
  def contains(objIn:EnvObject): Boolean = {
    if (this.containedObjects.contains(objIn)) return true
    // Otherwise
    return false
  }

  def equals(that:EnvObject):Boolean = {
    if (this.uuid == that.uuid) return true
    // Otherwise
    return false
  }

  /*
   * Contains (recursive)
   */
  def containsRecursive(objIn:EnvObject):Boolean = {
    if (this.contains(objIn)) return true
    if (this.getContainer().isDefined) {
      // If this object is in a container, then continue searching by recursing down through the containers
      return this.containsRecursive(objIn)
    } else {
      // If this object is not in a container, then we've hit the bottom of the object tree, and this container isn't in it
      return false
    }
  }

  /*
   * Get container of type (recursive), as long as it's accessible
   */
  def getContainerRecursiveOfType[T:ClassTag]():Option[EnvObject] = {
    // Step 1: Check this object's container
    val container = this.getContainer()
    if (container.isEmpty) return None
    container.get match {
      case x:T => return Some(x)
      case _ => { }
    }

    // Step 2: Recurse, if this container is open/accessible
    if ((this.propContainer.isDefined) && (this.propContainer.get.isOpen)) {
      return this.getContainer().get.getContainerRecursiveOfType[T]()
    }

    // Default return
    None
  }

  // Get all the containers that this object is in, down until the root of the object's world tree
  def getContainersRecursive():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]

    // This objects container
    val container = this.getContainer()
    if (container.isDefined) {
      out.append(container.get)
      // Recurse through the container's container
      out.insertAll(out.length, container.get.getContainersRecursive)
    }

    // Return
    out.toArray
  }

  /*
   * Helpers
   */
  def getName():String = this.name

  def setName(strIn:String) { this.name = strIn }

  def getType():String = this.objType

  def setType(strIn:String) { this.objType = strIn }

  // Visibility
  def isHidden():Boolean = this._isHidden
  def setHidden(value:Boolean) { this._isHidden = value }

  // The object name, with important descriptors added
  def getDescriptName(overrideName:String = ""):String = {
    // By default use this.name, unless an overrideName has been specified.
    var name = this.name
    if (overrideName.length > 0) name = overrideName

    // Check 1: Was on fire
    if (!this.isOnFire() && this.hasCombusted()) {
      return "burned " + name
    }

    // Check 2: Is on fire
    if (this.isOnFire()) {
      return name + " (on fire)"
    }

    // Otherwise
    return name
  }

  /*
   * Delete (remove) object from simulation
   */
  def delete(expelContents:Boolean = false): Unit = {
    // Expel the contents to the parent container (if enabled)
    if ((expelContents) && (this.getContainer().isDefined)) {
      this.moveAllContainedObjects( this.getContainer().get )
    }

    // Disconnect electrically (if connected)
    this.disconnectElectricalTerminals()

    // Remove from containers
    this.removeAndResetContainer()

    // Append special deleted flag, to notice the object when debugging if it happens to be left floating around in the simulation
    this.name += " (deleted)"
    this.deleted = true
  }

  def isDeleted():Boolean = this.deleted


  /*
   * Simulation methods (electrical conductivity)
   */
  def isElectricallyConnected():Boolean = {
    if (terminal1.isDefined && terminal1.get.propElectricalConnection.get.size() > 0) return true
    if (terminal2.isDefined && terminal2.get.propElectricalConnection.get.size() > 0) return true
    return false
  }

  def hasUnpolarizedElectricalTerminals():Boolean = {
    if (terminal1.isDefined && terminal2.isDefined) return true
    // Otherwise
    return false
  }

  // Given one terminal, get the other (connected) terminal.
  def getOtherElectricalTerminal(terminalIn:EnvObject):Option[Terminal] = {
    if ((terminal1.isEmpty) || (terminal2.isEmpty)) return None

    if (terminalIn == terminal1.get) return terminal2
    if (terminalIn == terminal2.get) return terminal1

    // Otherwise
    return None
  }

  def getUnconnectedElectricalTerminal():Option[Terminal] = {
    if ((terminal1.isEmpty) || (terminal2.isEmpty)) return None

    if (terminal1.get.propElectricalConnection.get.size() == 0) return terminal1
    if (terminal2.get.propElectricalConnection.get.size() == 0) return terminal2

    // Otherwise
    return None
  }

  def disconnectElectricalTerminals() {
    if (terminal1.isDefined) this.terminal1.get.disconnect()
    if (terminal2.isDefined) this.terminal2.get.disconnect()
  }


  /*
   * Simulation methods (devices)
   */
  def useWith(patientObj:EnvObject):(Boolean, String) = {
    return (false, "")
  }

  /*
   * Simulation methods (combustion)
   */

  // Returns true if the environment is currently on fire, or has been on fire.
  def hasCombusted():Boolean = {
    if (this.propMaterial.isEmpty) return false
    return this.propMaterial.get.hasCombusted
  }

  def isOnFire():Boolean = {
    if (this.propMaterial.isEmpty) return false
    return this.propMaterial.get.isCombusting
  }


  /*
   * Text-based simulation methods
   */
  // Tick completion
  def setTickProcessed() { this.tickCompleted = true }
  def clearTickProcessed() { this.tickCompleted = false }
  def wasTickProcessed():Boolean = this.tickCompleted

  def clearTickProcessedRecursive(indentLevel:Int = 0): Unit = {
    // Clear for this object
    this.clearTickProcessed()

    // Run tick for all objects further down in the object tree
    for (containedObj <- this.getContainedObjects()) {
      containedObj.clearTickProcessedRecursive(indentLevel+1)
    }
    for (portalObj <- this.getPortals()) {
      portalObj.clearTickProcessedRecursive(indentLevel+1)
    }
  }


  def tick():Boolean = {
    // Was tick already processed
    if (this.wasTickProcessed()) return false

    /*
    print ("TICK: " + this.toStringMinimal())
    if (this.getContainer().isDefined) {
      print("\t on " + this.getContainer().get.name)
    }
    println("")
     */

    // Combustion: Handle object combustion
    Combustion.combustionTick(this)

    val containedObjs = this.getContainedObjects().toArray.sortBy(_.uuid)

    // Heat transfer: Conductive heat transfer between this container and all objects in the container (container to obj)
    for (containedObj <- containedObjs) {
      HeatTransfer.heatTransferTouchingObjects(this, containedObj)
    }

    // Heat transfer: Conductive heat transfer between all objects in this container (obj to obj)
    for (i <- 0 until containedObjs.length) {
      for (j <- 0 until i) {
        if (i != j) {
          HeatTransfer.heatTransferTouchingObjects(containedObjs(i), containedObjs(j) )
        }
      }
    }

    // State of matter: Change state of matter based on temperature
    StateOfMatter.ChangeOfState(this)

    // Electrical conductivity: Potentially conduct electricity, if an electrical conductor and connected to other conductors
    ElectricalConductivity.unpolarizedElectricalConductivityTick(this, activateDeviceIfPowered = false)


    // Run tick for all objects further down in the object tree
    for (containedObj <- containedObjs) {
      containedObj.tick()
    }
    for (portalObj <- this.getPortals().toArray.sortBy(_.uuid)) {      //## TODO: Verify that the portal tick was run only once?
      portalObj.tick()
    }


    // Set tick processed
    this.setTickProcessed()

    // Return
    true
  }

  def getReferents():Set[String] = {
    val out = mutable.Set[String]()
    out.add("object")
    out.add(this.name)
    out.add(this.getDescriptName())
    // Return
    out.toSet
  }

  // Enumerates referents with their container (e.g. water becomes water, water in pot) to allow for disambiguation
  def getReferentsWithContainers(perspectiveContainer:EnvObject):Set[String] = {
    val out = mutable.Set[String]()
    var referents = this match {
      case x:Portal => x.getReferents(perspectiveContainer)
      case _ => this.getReferents()
    }

    for (ref <- referents) {
      if (ref.trim.length > 0) {      // Ensure that the referent has text (PJ: May 27/2022)
        out.add(ref.toLowerCase)
        val container = this.getContainer()
        if (container.isDefined) {
          for (containerRef <- container.get.getReferents()) {
            out.add((ref + " in " + containerRef).toLowerCase)
            out.add((ref + " on " + containerRef).toLowerCase)
          }
        }
      }
    }

    out.toSet.filter(_.length > 1)
  }

  def getDescription(mode:Int = MODE_CURSORY_DETAIL):String = {
    return "An object, called " + this.getDescriptName() + ", of type " + this.objType
  }

  // If the object is hidden, returns None
  def getDescriptionSafe(mode:Int = MODE_CURSORY_DETAIL):Option[String] = {
    if (this.isHidden()) return None
    Some(this.getDescription(mode))
  }

  /*
   * Operators
   */
  override def equals(that:Any):Boolean = {
    that match {
      case that:EnvObject => {
        if (this.uuid == that.uuid) {
          return true
        } else {
          return false
        }
      }
      case _ => return false
    }
  }


  /*
   * String methods
   */
  def toStringIncludingContents(indent:Int = 0):String = {
    val os = new StringBuilder

    // This object
    os.append( ("\t" * indent) + this.toString() + "\n")
    // Recurse through containing objects
    for (obj <- this.getContainedObjects()) {
      os.append( obj.toStringIncludingContents(indent+1))
    }

    os.toString()
  }

  def toStringMinimal():String = {
    val os = new StringBuilder
    val displayProps = Array("name", "type")

    os.append("ObjectID (" + uuid + ", name: " + this.name + ", type: " + this.objType + ")")

    os.toString()
  }

  override def toString(): String = {
    val os = new mutable.StringBuilder()

    os.append("ObjectID (" + uuid + ", name: " + this.name + ", type: " + this.objType + ")")

    // Object Contents
    os.append("), Contents (")
    val contentNames = new ArrayBuffer[String]()
    for (obj <- this.getContainedObjects()) {
      contentNames.append(obj.getName() + "/" + obj.getType())
    }
    os.append( contentNames.mkString(", ") )

    os.append(")")

    // Return
    os.toString()
  }

  def toJSON():String = {
    val os = new StringBuilder()
    os.append("{")
    os.append("\"uuid\":\"" + this.uuid + "\",")
    os.append("\"name\":\"" + this.name + "\",")
    os.append("\"type\":\"" + this.objType + "\",")
    os.append("\"isDeleted\":" + this.isDeleted + ",")

    // Properties
    os.append("\"propMaterial\":" + (if (this.propMaterial.isEmpty) "null" else this.propMaterial.get.toJSON()) + ",")
    os.append("\"propEdibility\":" + (if (this.propEdibility.isEmpty) "null" else this.propEdibility.get.toJSON()) + ",")
    os.append("\"propContainer\":" + (if (this.propContainer.isEmpty) "null" else this.propContainer.get.toJSON()) + ",")
    os.append("\"propDevice\":" + (if (this.propDevice.isEmpty) "null" else this.propDevice.get.toJSON()) + ",")
    os.append("\"propHeatSource\":" + (if (this.propHeatSource.isEmpty) "null" else this.propHeatSource.get.toJSON()) + ",")
    os.append("\"propCoolingSource\":" + (if (this.propCoolingSource.isEmpty) "null" else this.propCoolingSource.get.toJSON()) + ",")

    os.append("\"propPortal\":" + (if (this.propPortal.isEmpty) "null" else this.propPortal.get.toJSON()) + ",")
    os.append("\"propMoveable\":" + (if (this.propMoveable.isEmpty) "null" else this.propMoveable.get.toJSON()) + ",")
    os.append("\"propElectricalConnection\":" + (if (this.propElectricalConnection.isEmpty) "null" else this.propElectricalConnection.get.toJSON()) + ",")
    os.append("\"propLife\":" + (if (this.propLife.isEmpty) "null" else this.propLife.get.toJSON()) + ",")

    // os.append("\"propChromosomePairs\":" + (if (this.propChromosomePairs.isEmpty) "null" else this.propChromosomePairs.get.toJSON()) + ",")
    // os.append("\"propPollination\":" + (if (this.propPollination.isEmpty) "null" else this.propPollination.get.toJSON()) + ",")

    // Contents
    val contents_json = new ArrayBuffer[String]()
    for (obj <- this.getContainedObjects()) {
      contents_json.append("\"" + obj.name + "-" + obj.uuid + "\": " + obj.toJSON())
    }

    os.append("\"contents\": " + contents_json.mkString("{", ",", "}"))
    os.append("}")
    return os.toString()
  }

}

object EnvObject {
  val MODE_CURSORY_DETAIL  =   0
  val MODE_DETAILED        =   1

  private[scienceworld] def uuidOrderedSet[T <: EnvObject](objects:Iterable[T]):Set[T] = {
    implicit val ordering:Ordering[T] = Ordering.by[T, Long](_.uuid)
    scala.collection.immutable.TreeSet.empty[T] ++ objects
  }
}
