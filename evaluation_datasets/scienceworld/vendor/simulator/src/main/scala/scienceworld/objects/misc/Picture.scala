package scienceworld.objects.misc

import scienceworld.properties.{IsNotContainer, MoveableProperties, PaperProp}
import scienceworld.struct.EnvObject
import scienceworld.struct.EnvObject._

import scala.util.Random

class Picture extends EnvObject {
  this.name = "document"
  var description = "document"
  var artist = "This is a sample document."

  this.propMaterial = Some(new PaperProp())
  this.propContainer = Some( new IsNotContainer() )
  this.propDevice = None
  this.propMoveable = Some(new MoveableProperties(isMovable = true))

  override def getReferents(): Set[String] = {
    Set(this.name, this.name + " of " + this.description, this.getDescriptName(), this.getDescriptName() + " of " + this.description)
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder

    if (mode == MODE_CURSORY_DETAIL) return "a " + this.getDescriptName()

    if (mode == MODE_DETAILED) {
      os.append("a " + this.getDescriptName() + " of " + description + ". ")
      os.append(" The artist is listed as " + this.artist + ". ")
    }

    os.toString
  }

}


object Picture {
  val pictureTypes = Array("picture", "drawing", "painting", "finger painting")
  val subjects = Array("a cow", "a chicken", "a farm", "a lush green meadow", "rolling hills", "a wintery mountain", "a boat crossing a river", "the moon", "abstract shapes", "two people playing")
  val artist = Array("Alexandra", "Owen", "Bob", "Lily")


  def mkRandom():EnvObject = {
    val out = new Picture()
    out.name = pictureTypes( Random.nextInt(pictureTypes.length) )
    out.description = subjects( Random.nextInt(subjects.length) )
    out.artist = artist( Random.nextInt(artist.length) )

    // Return
    out
  }

}
