package language.struct

import util.UniqueIdentifier

import scala.collection.mutable
import scala.collection.mutable.ArrayBuffer

class EnvObject {
  val PROPNAME_CONTAINED_OBJECTS = "containedObjects"
  val PROPNAME_CONTAINER         = "container"

  // Properties
  val properties = mutable.Map[String, DynamicValue]()

  // Contained objects
  private val containedObjects = mutable.Set[EnvObject]()
  private var inContainer:Option[EnvObject] = None

  // Unique identifier
  val uuid = UniqueIdentifier.getNextID()


  /*
   * Properties
   */
  def getProperty(name:String):Option[DynamicValue] = {
    if (name == PROPNAME_CONTAINED_OBJECTS) return Some(DynamicValue.mkArray(this.getContainedObjects().toArray))
    if (name == PROPNAME_CONTAINER) {
      if (this.getContainer().isEmpty) throw new RuntimeException("ERROR: Accessing object.container property, for an object without a container.\n" + this.toString())
      return Some(new DynamicValue(this.getContainer().get))
    }
    if (!this.properties.contains(name)) return None
    return this.properties.get(name)
  }

  def setProperty(name:String, value:DynamicValue): Unit = {
    if (name == PROPNAME_CONTAINED_OBJECTS) println("WARNING: Object property (" + PROPNAME_CONTAINED_OBJECTS + ") is virtual, and can only be read, not set.  Changes not made.")
    if (name == PROPNAME_CONTAINER) println("WARNING: Object property (" + PROPNAME_CONTAINER + ") is virtual, and can only be read, not set.  Changes not made.")
    this.properties(name) = value
  }

  def hasProperty(name:String):Boolean = {
    this.properties.contains(name)
  }

  def getPropertyNames():Array[String] = {
    (this.properties.keySet.toArray ++ Array(PROPNAME_CONTAINED_OBJECTS)).sorted
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
   * Object containment
   */

  def getContainer():Option[EnvObject] = this.inContainer

  def getContainedObjects():Set[EnvObject] = EnvObject.uuidOrderedSet(this.containedObjects)

  // Add an object to this container
  def addObject(objIn:EnvObject): Unit = {
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
   * Helpers
   */
  def getName():String = {
    val name = this.getProperty(EnvObject.OBJECT_NAME)
    if (name.isEmpty) return "None"
    return name.get.getString().getOrElse("None")
  }

  def setName(strIn:String): Unit = {
    this.setProperty(EnvObject.OBJECT_NAME, new DynamicValue(strIn))
  }

  def getType():String = {
    val name = this.getProperty(EnvObject.OBJECT_TYPE)
    if (name.isEmpty) return "None"
    return name.get.getString().getOrElse("None")
  }

  def setType(strIn:String): Unit = {
    this.setProperty(EnvObject.OBJECT_TYPE, new DynamicValue(strIn))
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

    os.append("ObjectID (" + uuid + "), ")
    os.append("Properties (")

    for (propName <- displayProps) {
      if (this.properties.contains(propName)) {
        var propValueSanitized = this.getProperty(propName).get.toString.replaceAll("\\n", "\\\\n")
        os.append(propName + " = " + propValueSanitized)
      }
    }

    os.append(")")

    os.toString()
  }

  override def toString(): String = {
    val os = new mutable.StringBuilder()

    os.append("ObjectID (" + uuid + ", ")
    // Quick properties
    val displayProps = Array("name", "type")
    for (propName <- displayProps) {
      if (this.properties.contains(propName)) {
        var propValueSanitized = this.getProperty(propName).get.toString.replaceAll("\\n", "\\\\n")
        os.append(propName + " = " + propValueSanitized + ",")
      }
    }
    os.append("), ")

    os.append("Properties (")



    // Property Values
    val propValues = new ArrayBuffer[String]()
    for (propName <- this.getPropertyNames()) {
      val prop = this.getProperty(propName).get
      var propValue:String = ""
      if (prop.isObject()) {
        propValue = prop.getObject().get.toStringMinimal()
      } else {
        propValue = this.getProperty(propName).get.toString
      }
      var propValueSanitized = propValue.replaceAll("\\n", "\\\\n")
      propValues.append(propName + " = " + propValueSanitized)
    }
    os.append( propValues.mkString(", ") )

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

}


object EnvObject {
  val OBJECT_NAME       = "name"
  val OBJECT_TYPE       = "type"

  private[language] def uuidOrderedSet(objects:Iterable[EnvObject]):Set[EnvObject] = {
    implicit val ordering:Ordering[EnvObject] = Ordering.by[EnvObject, Long](_.uuid)
    scala.collection.immutable.TreeSet.empty[EnvObject] ++ objects
  }
}
