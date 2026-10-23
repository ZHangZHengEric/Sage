package scienceworld.objects.containers

import main.scala.scienceworld.runtime.SimplifierProcessor
import scienceworld.objects.document.Book
import scienceworld.objects.substance.Water
import scienceworld.properties._
import scienceworld.struct.EnvObject
import scienceworld.struct.EnvObject._
import util.StringHelpers

import scala.collection.mutable
import scala.util.Random

class Container extends EnvObject {
  this.name = "container"
  this.propContainer = Some(new IsContainer())

  // Make a set of more specific references to this container based on its content (e.g. a jug 'containing blue paint')
  def mkContentReferences(existingReferents:Set[String]):Set[String] = {
    val out = mutable.Set[String]()

    for (ref <- existingReferents) {
      val contents = this.getContainedObjects(includeHidden = false)
      var newRef = ""
      if (contents.size == 0) {
        newRef = ref + " containing nothing"
      } else {
        val contentNames = contents.map(_.getDescriptName()).toArray.sorted
        newRef = ref + " containing " + contentNames.mkString(" and ")
      }
      out.add(ref)
      out.add(newRef)
    }

    // Return
    out.toSet
  }

  override def getReferents(): Set[String] = {
    Set("container", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    val containedObjects = this.getContainedObjectsAndPortals()
    if (containedObjects.size == 0) {
      return "an empty " + this.getDescriptName()
    } else {
      return "a " + this.getDescriptName() + " (containing " + StringHelpers.objectListToStringDescription(containedObjects, this, mode=MODE_CURSORY_DETAIL, multiline = false) + ")"
    }
  }

}


/*
 * Base class for canonical containers used to pick up other things
 */
class Cup extends Container {

}

/*
 * Pots
 */

class MetalPot extends Cup {
  this.name = "metal pot"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new SteelProp())

  override def getReferents(): Set[String] = {
    this.mkContentReferences( Set("pot", "metal pot", this.name, this.getDescriptName()) )
  }

}


/*
 * Cups
 */
class GlassCup extends Cup {
  this.name = "glass cup"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new GlassProp())

  override def getReferents(): Set[String] = {
    this.mkContentReferences( Set("cup", "glass cup", this.name, this.getDescriptName()) )
  }

}


class PlasticCup extends Cup {
  this.name = "plastic cup"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new PlasticProp())

  override def getReferents(): Set[String] = {
    this.mkContentReferences( Set("cup", "plastic cup", this.name, this.getDescriptName()) )
  }

}

class WoodCup extends Cup {
  this.name = "wood cup"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new WoodProp())

  override def getReferents(): Set[String] = {
    this.mkContentReferences( Set("cup", "wood cup", this.name, this.getDescriptName()) )
  }

}

class TinCup extends Cup {
  this.name = "tin cup"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new TinProp())

  override def getReferents(): Set[String] = {
    this.mkContentReferences( Set("cup", "tin cup", this.name, this.getDescriptName()) )
  }


}

class PaperCup extends Cup {
  this.name = "paper cup"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new PaperProp())

  override def getReferents(): Set[String] = {
    this.mkContentReferences( Set("cup", "paper cup", this.name, this.getDescriptName()) )
  }

}

class CeramicCup extends Cup {
  this.name = "ceramic cup"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new CeramicProp())

  override def getReferents(): Set[String] = {
    this.mkContentReferences( Set("cup", "ceramic cup", this.name, this.getDescriptName()) )
  }

}

class WoodBowl extends Cup {
  this.name = "bowl"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new WoodProp())

  override def getReferents(): Set[String] = {
    this.mkContentReferences( Set("bowl", this.propMaterial.get.substanceName + " bowl", this.name, this.getDescriptName()) )
  }

}

class Jug extends Cup {
  this.name = "jug"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new PlasticProp())

  override def getReferents(): Set[String] = {
    this.mkContentReferences( Set("jug", this.name, this.getDescriptName()) )
  }

}


class GlassJar extends Cup {
  this.name = "glass jar"
  this.propContainer = Some(new IsContainer())
  this.propMaterial = Some(new GlassProp())

  override def getReferents(): Set[String] = {
    this.mkContentReferences( Set("jar", "glass jar", this.name, this.getDescriptName()) )
  }

}

/*
 * Flower pot
 */
class FlowerPot extends Container {
  this.name = "flower pot"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new CeramicProp())

  override def tick(): Boolean = {
    // DEBUG: Add water if there is none

    //println ("### FLOWER POT: Infinite water")
    if (SimplifierProcessor.isSimplificationEnabled(SimplifierProcessor.SIMPLIFICATION_SELF_WATERING_FLOWER_POTS)) {
      if (this.getContainedObjectsOfType[Water]().size == 0) {
        this.addObject(new Water())
      }
    }

    super.tick()
  }


  override def getReferents(): Set[String] = {
    this.mkContentReferences( Set("pot", "flower pot", this.name, this.getDescriptName()) )
  }

}

// Explicit self-watering flower pot, that's self watering regardless of whether the simplification is enabled or not
class SelfWateringFlowerPot extends Container {
  this.name = "self watering flower pot"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new CeramicProp())

  override def tick(): Boolean = {
    // DEBUG: Add water if there is none
    if (this.getContainedObjectsOfType[Water]().size == 0) {
      this.addObject(new Water())
    }

    super.tick()
  }

  override def getReferents(): Set[String] = {
    this.mkContentReferences( Set("pot", "flower pot", this.name, this.getDescriptName()) )
  }

}



/*
 * Shelf
 */
class BookShelf extends Container {
  this.name = "book shelf"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new WoodProp())

  override def getReferents(): Set[String] = {
    this.mkContentReferences( Set("shelf", "book shelf", this.name, this.getDescriptName()) )
  }

}

object BookShelf {

  def mkRandom(): EnvObject = {
    val numBooks = Random.nextInt(4)

    val bookshelf = new BookShelf()
    for (i <- 0 until numBooks) {
      bookshelf.addObject( Book.mkRandom() )
    }

    return bookshelf
  }
}
