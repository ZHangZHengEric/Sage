package scienceworld.objects.location

import scienceworld.objects.environmentoutside.Ground
import scienceworld.objects.substance.Air
import scienceworld.properties.{ContainerProperties, IsContainer, IsOpenUnclosableContainer, MoveableProperties}
import scienceworld.struct.EnvObject
import scienceworld.struct.EnvObject._
import util.StringHelpers


class Location extends EnvObject {
  this.name = "location"

  propMoveable = Some( new MoveableProperties(isMovable = false) )
  propContainer = Some( new IsOpenUnclosableContainer() )

  override def getReferents(): Set[String] = {
    Set("location", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder()

    os.append("A " + this.getDescriptName() + ". ")
    os.append("In this location, you see: ")
    os.append( StringHelpers.objectListToStringDescription(this.getContainedObjectsAndPortals(), perspectiveContainer=this, multiline = true)  )
    os.append(".")

    os.toString()
  }

}


// Object tree root
class Universe extends Location {
  this.name = "universe"

  override def getReferents(): Set[String] = {
    Set("universe", this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder()

    os.append("A " + this.getDescriptName() + ". ")
    os.append("In this Universe, you see: ")
    os.append( StringHelpers.objectListToStringDescription(this.getContainedObjectsAndPortals(), perspectiveContainer=this, multiline = true)  )
    os.append(".")

    os.toString()
  }
}


// One room (i.e. in a house/other structure)
class Room(_name:String) extends Location {
  def this() = this(_name = "room")

  this.name = _name

  // Add air
  val air = new Air()
  air.propMaterial.get.temperatureC = 25.0f
  this.addObject( air )


  override def getReferents(): Set[String] = {
    Set("room", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder()

    os.append("This room is called the " + this.getDescriptName() + ". ")
    os.append("In it, you see: \n")
    os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = true)  )

    os.append("You also see:\n")
    os.append( StringHelpers.portalListToStringDescription(this.getPortals(), perspectiveContainer=this, multiline = true)  )

    os.toString()
  }
}


// Outside
class Outside(_name:String) extends Location {
  def this() = this(_name = "outside")

  this.name = _name

  // Add air
  val air = new Air()
  air.propMaterial.get.temperatureC = 25.0f
  this.addObject( air )

  // Add ground
  val ground = new Ground()
  this.addObject(ground)


  override def getReferents(): Set[String] = {
    Set("outside", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder()

    os.append("This outside location is called the " + this.getDescriptName() + ". ")
    os.append("Here you see: \n")
    os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = true)  )

    os.append("You also see:\n")
    os.append( StringHelpers.portalListToStringDescription(this.getPortals(), perspectiveContainer=this, multiline = true)  )

    os.toString()
  }
}
