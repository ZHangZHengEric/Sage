package scienceworld.objects.devices

import scienceworld.properties.{HeatSourceProperties, HeatSourcePropertiesBlastFurnace, HeatSourcePropertiesOven, HeatSourcePropertiesStove, IsContainer, IsOpenUnclosableContainer, MoveableProperties}
import scienceworld.processes.HeatTransfer
import scienceworld.struct.EnvObject._
import util.StringHelpers

class HeatSource extends Device {
  this.name = "heat source"

  this.propHeatSource = Some(new HeatSourcePropertiesStove())

  override def tick():Boolean = {

    // Step 1: Heat transfer between this heat source and all contained objects
    for (containedObj <- this.getContainedObjects()) {
      HeatTransfer.heatTransferHeatSource(this, containedObj)
    }

    // Step 2: Tick
    super.tick()
  }

}




class Stove extends HeatSource {
  this.name = "stove"

  this.propHeatSource = Some(new HeatSourcePropertiesStove)
  this.propContainer = Some( new IsOpenUnclosableContainer() )
  this.propMoveable = Some(new MoveableProperties(isMovable = false))

  override def tick():Boolean = {
    // If it's activated, then set max temp.  If deactivated, set temp to off.
    if (this.propDevice.isDefined) {
      if (this.propDevice.get.isActivated) {
        this.propHeatSource.get.setOnMax()
      } else {
        this.propHeatSource.get.setOff()
      }
    }

    super.tick()
  }

  override def getReferents():Set[String] = {
    Set("stove", this.name)
  }

  override def getDescription(mode:Int):String = {
    val os = new StringBuilder

    os.append("a " + this.name + ", which is turned ")
    if (this.propDevice.get.isActivated) { os.append("on") } else { os.append("off") }
    os.append(". ")

    os.append("On the stove is: ")
    os.append( StringHelpers.objectListToStringDescription(this.getContainedObjectsAndPortals(), perspectiveContainer=this, multiline = false)  )
    os.append(".")

    os.toString()
  }

}

class HotPlate extends HeatSource {
  this.name = "hot plate"

  this.propHeatSource = Some(new HeatSourcePropertiesStove)
  this.propContainer = Some( new IsOpenUnclosableContainer() )
  this.propMoveable = Some(new MoveableProperties(isMovable = false))

  override def tick():Boolean = {
    // If it's activated, then set max temp.  If deactivated, set temp to off.
    if (this.propDevice.isDefined) {
      if (this.propDevice.get.isActivated) {
        this.propHeatSource.get.setOnMax()
      } else {
        this.propHeatSource.get.setOff()
      }
    }

    super.tick()
  }

  override def getReferents():Set[String] = {
    Set("hot plate", this.name)
  }

  override def getDescription(mode:Int):String = {
    val os = new StringBuilder

    os.append("a " + this.name + ", which is turned ")
    if (this.propDevice.get.isActivated) { os.append("on") } else { os.append("off") }
    os.append(". ")

    os.append("On the hot plate is: ")
    os.append( StringHelpers.objectListToStringDescription(this.getContainedObjectsAndPortals(), perspectiveContainer=this, multiline = false)  )
    os.append(".")

    os.toString()
  }

}

class Oven extends HeatSource {
  this.name = "oven"

  this.propHeatSource = Some(new HeatSourcePropertiesOven)
  this.propContainer = Some( new IsContainer() )
  this.propMoveable = Some(new MoveableProperties(isMovable = false))

  override def tick():Boolean = {
    // If it's activated, then set max temp.  If deactivated, set temp to off.
    if (this.propDevice.isDefined) {
      if (this.propDevice.get.isActivated) {
        this.propHeatSource.get.setOnMax()
      } else {
        this.propHeatSource.get.setOff()
      }
    }

    super.tick()
  }

  override def getReferents():Set[String] = {
    Set("oven", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int):String = {
    val os = new StringBuilder


    os.append("a " + this.getDescriptName() + ", which is turned ")
    if (this.propDevice.get.isActivated) { os.append("on") } else { os.append("off") }
    os.append(". ")

    os.append("The " + this.getDescriptName() + " door is ")
    if (this.propContainer.get.isOpen) {
      os.append("open. ")
    } else {
      os.append("closed. ")
    }

    if (this.propContainer.get.isOpen) {
      if (mode == MODE_CURSORY_DETAIL) {
        os.append("In the " + this.getDescriptName() + " is: ")
        os.append( StringHelpers.objectListToStringDescription(this.getContainedObjectsAndPortals(), perspectiveContainer=this, multiline = false)  )
        os.append(".")
      } else if (mode == MODE_DETAILED) {
        os.append("In the " + this.getDescriptName() + " is: \n")
        os.append( StringHelpers.objectListToStringDescription(this.getContainedObjectsAndPortals(), perspectiveContainer=this, multiline = true)  )
      }
    }

    os.toString
  }

}

class BlastFurnace extends HeatSource {
  this.name = "blast furnace"

  this.propHeatSource = Some(new HeatSourcePropertiesBlastFurnace)
  this.propContainer = Some( new IsContainer() )
  this.propMoveable = Some(new MoveableProperties(isMovable = false))

  override def tick():Boolean = {
    // If it's activated, then set max temp.  If deactivated, set temp to off.
    if (this.propDevice.isDefined) {
      if (this.propDevice.get.isActivated) {
        this.propHeatSource.get.setOnMax()
      } else {
        this.propHeatSource.get.setOff()
      }
    }

    super.tick()
  }

  override def getReferents():Set[String] = {
    Set("furnace", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int):String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + ", which is turned ")
    if (this.propDevice.get.isActivated) { os.append("on") } else { os.append("off") }
    os.append(". ")

    os.append("The " + this.getDescriptName() + " door is ")
    if (this.propContainer.get.isOpen) {
      os.append("open. ")
    } else {
      os.append("closed. ")
    }

    if (this.propContainer.get.isOpen) {
      if (mode == MODE_CURSORY_DETAIL) {
        os.append("In the " + this.getDescriptName() + " is: ")
        os.append( StringHelpers.objectListToStringDescription(this.getContainedObjectsAndPortals(), perspectiveContainer=this, multiline = false)  )
        os.append(".")
      } else if (mode == MODE_DETAILED) {
        os.append("In the " + this.getDescriptName() + " is: \n")
        os.append( StringHelpers.objectListToStringDescription(this.getContainedObjectsAndPortals(), perspectiveContainer=this, multiline = true)  )
      }
    }

    os.toString
  }

}
