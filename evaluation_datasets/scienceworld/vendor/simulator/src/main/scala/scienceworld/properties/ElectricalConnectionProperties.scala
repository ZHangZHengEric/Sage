package scienceworld.properties

import scienceworld.struct.EnvObject
import scienceworld.struct.EnvObject._

import scala.collection.mutable
import scala.collection.mutable.ArrayBuffer

// A storage class for an electrical connection point (e.g. anode, cathode)
class ElectricalConnectionProperties {
  val MAX_CONNECTIONS = 1
  val connectedTo = mutable.Set[EnvObject]()

  /*
   * Accessors
   */
  def getConnections():Set[EnvObject] = EnvObject.uuidOrderedSet(this.connectedTo)

  def addConnection(obj:EnvObject): Boolean = {
    if (this.isAtMaxConnections()) return false     // Fail if we've already connected the maximum number of components to this connection point
    connectedTo.add(obj)
    return true
  }

  def removeConnection(obj:EnvObject): Boolean = {
    if (connectedTo.contains(obj)) {
      connectedTo.remove(obj)
      return true
    }
    // Otherwise
    return false
  }

  def isConnected(obj:EnvObject):Boolean = {
    if (connectedTo.contains(obj)) return true
    // Otherwise
    return false
  }

  def size():Int = {
    return this.connectedTo.size
  }

  def isAtMaxConnections():Boolean = {
    if (this.size >= MAX_CONNECTIONS) return true
    // Otherwise
    return false
  }

  /*
   * String description of connections
   */
  def getConnectedToStr():String = {
    // Case: not connected
    if (this.connectedTo.size == 0) return "nothing"
    // Case: connected to one or more objects
    this.getConnections().toArray.map(_.getDescription(MODE_CURSORY_DETAIL)).mkString(", ")
  }


  def toJSON():String = {
    val os = new StringBuilder()
    os.append("{")

    // Connected objects
    val connection_json = new ArrayBuffer[String]()
    for (obj <- this.connectedTo.toArray.sortBy(_.uuid)) {
      connection_json.append("\"" + obj.uuid + "\"")
    }

    os.append("\"connectedTo\": " + connection_json.mkString("[", ",", "]"))
    os.append("}")

    return os.toString()
  }

}
