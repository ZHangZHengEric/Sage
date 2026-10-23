package scienceworld.tasks.goals

import scienceworld.struct.EnvObject
import scienceworld.struct.EnvObject._

import scala.collection.mutable

// MaxSize represents the maximum number of objects that can be simultaneously monitored
class ObjMonitor(val maxSize:Int = 1) {
  val monitoredObjects = mutable.Set[EnvObject]()

  /*
   * Accessors
   */
  def clearMonitoredObjects() = { this.monitoredObjects.clear() }

  def getMonitoredObjects():Set[EnvObject] = EnvObject.uuidOrderedSet(this.monitoredObjects)

  def addMonitor(obj:EnvObject): Boolean = {
    if (this.monitoredObjects.size >= maxSize) return false
    this.monitoredObjects.add(obj)
    return true
  }

  def removeMonitor(obj:EnvObject): Unit = {
    this.monitoredObjects.remove(obj)
  }


  /*
   * String methods
   */
  override def toString():String = {
    val os = new StringBuilder

    val objs = getMonitoredObjects().toArray
    os.append("Monitored Objects:\n")
    for (i <- 0 until objs.length) {
      os.append("\t" + i + ":\t" + objs(i).toStringMinimal())
    }

    // Return
    os.toString
  }
}
