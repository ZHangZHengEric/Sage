package scienceworld.objects.containers.furniture

import scienceworld.objects.containers.Container
import scienceworld.properties.{IsContainer, IsOpenUnclosableContainer, SteelProp, WoodProp}
import scienceworld.struct.EnvObject._
import util.StringHelpers


/*
 * Tables/Desks/etc
 */
class WoodTable extends Container {
  this.name = "table"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new WoodProp())

  override def getReferents(): Set[String] = {
    Set("table", this.propMaterial.get.substanceName + " table", this.name, this.getDescriptName())
  }


  override def getDescription(mode: Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + ". ")

    if (mode == MODE_CURSORY_DETAIL) {
      os.append("On the " + this.getDescriptName() + " is: ")
      os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = false)  )
      os.append(".")
    } else if (mode == MODE_DETAILED) {
      os.append("On the " + this.getDescriptName() + " is: \n")
      os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = true)  )
    }

    os.toString
  }

}

class SteelTable extends Container {
  this.name = "table"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new SteelProp())

  override def getReferents(): Set[String] = {
    Set("table", this.propMaterial.get.substanceName + " table", this.name, this.getDescriptName())
  }


  override def getDescription(mode: Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + ". ")

    if (mode == MODE_CURSORY_DETAIL) {
      os.append("On the " + this.getDescriptName() + " is: ")
      os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = false)  )
      os.append(".")
    } else if (mode == MODE_DETAILED) {
      os.append("On the " + this.getDescriptName() + " is: \n")
      os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = true)  )
    }

    os.toString
  }

}

class Desk extends Container {
  this.name = "desk"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new WoodProp())

  // Create a drawer
  val drawer = new Drawer()
  this.addObject(drawer)

  override def getReferents(): Set[String] = {
    Set("desk", this.propMaterial.get.substanceName + " desk", this.name, this.getDescriptName())
  }


  override def getDescription(mode: Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + ". ")

    if (mode == MODE_CURSORY_DETAIL) {
      os.append("On the " + this.getDescriptName() + " is: ")
      os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = false)  )
      os.append(".")
    } else if (mode == MODE_DETAILED) {
      os.append("On the " + this.getDescriptName() + " is: \n")
      os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = true)  )
    }

    os.toString
  }

}

class Counter extends Container {
  this.name = "counter"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new WoodProp())

  // Create a drawer
  val drawer = new Drawer()
  this.addObject(drawer)

  override def getReferents(): Set[String] = {
    Set("counter", this.propMaterial.get.substanceName + " counter", this.name, this.getDescriptName())
  }


  override def getDescription(mode: Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + ". ")

    if (mode == MODE_CURSORY_DETAIL) {
      os.append("On the " + this.getDescriptName() + " is: ")
      os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = false)  )
      os.append(".")
    } else if (mode == MODE_DETAILED) {
      os.append("On the " + this.getDescriptName() + " is: \n")
      os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = true)  )
    }

    os.toString
  }

}


class Cupboard extends Container {
  this.name = "cupboard"
  this.propContainer = Some(new IsContainer())
  this.propMaterial = Some(new WoodProp())

  // Create a drawer
  val drawer = new Drawer()
  this.addObject(drawer)

  override def getReferents(): Set[String] = {
    Set("cupboard", this.propMaterial.get.substanceName + " cupboard", this.name, this.getDescriptName())
  }


  override def getDescription(mode: Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + ". ")

    os.append("The " + this.getDescriptName() + " door is ")
    if (this.propContainer.get.isOpen) {
      os.append("open. ")
    } else {
      os.append("closed. ")
    }

    if (this.propContainer.get.isOpen) {
      if (mode == MODE_CURSORY_DETAIL) {
        os.append("In the " + this.getDescriptName() + " is: ")
        os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = false)  )
        os.append(".")
      } else if (mode == MODE_DETAILED) {
        os.append("In the " + this.getDescriptName() + " is: \n")
        os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = true)  )
      }
    }

    os.toString
  }

}


class Closet extends Container {
  this.name = "closet"
  this.propContainer = Some(new IsContainer())
  this.propMaterial = Some(new WoodProp())


  override def getReferents(): Set[String] = {
    Set("closet", this.propMaterial.get.substanceName + " closet", this.name, this.getDescriptName())
  }


  override def getDescription(mode: Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + ". ")

    os.append("The " + this.getDescriptName() + " door is ")
    if (this.propContainer.get.isOpen) {
      os.append("open. ")
    } else {
      os.append("closed. ")
    }

    if (this.propContainer.get.isOpen) {
      if (mode == MODE_CURSORY_DETAIL) {
        os.append("In the " + this.getDescriptName() + " is: ")
        os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = false)  )
        os.append(".")
      } else if (mode == MODE_DETAILED) {
        os.append("In the " + this.getDescriptName() + " is: \n")
        os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = true)  )
      }
    }

    os.toString
  }

}

/*
 * Drawer
 */

class Drawer extends Container {
  this.name = "drawer"
  this.propContainer = Some(new IsContainer())
  this.propMaterial = Some(new WoodProp())

  override def getReferents(): Set[String] = {
    Set("drawer", this.propMaterial.get.substanceName + " table", this.name, this.getDescriptName())
  }


  override def getDescription(mode: Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName())

    if (mode == MODE_DETAILED) {
      os.append(". ")
      if (!this.propContainer.get.isOpen) {
        os.append(" The drawer is closed.")
      } else {
        if (mode == MODE_CURSORY_DETAIL) {
          os.append("In the " + this.getDescriptName() + " is: ")
          os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = false)  )
          os.append(".")
        } else if (mode == MODE_DETAILED) {
          os.append("In the " + this.getDescriptName() + " is: \n")
          os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = true)  )
        }
      }
    }

    os.toString
  }

}


/*
 * Bee Hive
 */
class BeeHive extends Container {
  this.name = "bee hive"
  this.propContainer = Some(new IsContainer())
  this.propMaterial = Some(new WoodProp())


  override def getReferents(): Set[String] = {
    Set("bee hive", "hive", "beehive", this.name, this.getDescriptName())
  }


  override def getDescription(mode: Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + ". ")

    os.append("The " + this.getDescriptName() + " door is ")
    if (this.propContainer.get.isOpen) {
      os.append("open. ")
    } else {
      os.append("closed. ")
    }

    if (this.propContainer.get.isOpen) {
      if (mode == MODE_CURSORY_DETAIL) {
        os.append("In the " + this.getDescriptName() + " is: ")
        os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = false)  )
        os.append(".")
      } else if (mode == MODE_DETAILED) {
        os.append("In the " + this.getDescriptName() + " is: \n")
        os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = true)  )
      }
    }

    os.toString
  }

}
