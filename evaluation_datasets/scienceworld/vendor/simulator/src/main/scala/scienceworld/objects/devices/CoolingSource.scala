package scienceworld.objects.devices

import scienceworld.properties.{CoolingSourcePropertiesFreezer, CoolingSourcePropertiesFridge, CoolingSourcePropertiesULTFreezer, HeatSourcePropertiesStove, IsActivableDeviceOn, IsContainer, IsOpenUnclosableContainer, MoveableProperties}
import scienceworld.processes.HeatTransfer
import util.StringHelpers

class CoolingSource extends Device {
  this.name = "cooling source"

  this.propCoolingSource = Some(new CoolingSourcePropertiesFridge)

  override def tick():Boolean = {

    // Step 1: Heat transfer between this heat source and all contained objects
    for (containedObj <- this.getContainedObjects()) {
      HeatTransfer.heatTransferCoolingSource(this, containedObj)
    }

    // Step 2: Tick
    super.tick()
  }

}




class Fridge extends CoolingSource {
  this.name = "fridge"

  this.propCoolingSource = Some(new CoolingSourcePropertiesFridge)
  this.propCoolingSource.get.setOnMin()
  this.propContainer = Some( new IsContainer() )
  this.propMoveable = Some(new MoveableProperties(isMovable = false))
  this.propDevice = Some(new IsActivableDeviceOn)

  override def tick():Boolean = {
    // If it's activated, then set min temp.  If deactivated, set temp to off.
    if (this.propDevice.isDefined) {
      if (this.propDevice.get.isActivated) {
        this.propCoolingSource.get.setOnMin()
      } else {
        this.propCoolingSource.get.setOff()
      }
    }

    super.tick()
  }

  override def getReferents():Set[String] = {
    Set("fridge", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int):String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName())
    // Only mention being off if it's off, but don't mention being on (since this is assumed).
    if (!this.propDevice.get.isActivated) {
      os.append(", which is turned ")
      if (this.propDevice.get.isActivated) { os.append("on") } else { os.append("off") }
    }
    os.append(". ")

    os.append("The " + this.getDescriptName() + " door is ")
    if (this.propContainer.get.isOpen) {
      os.append("open. ")
    } else {
      os.append("closed. ")
    }

    if (this.propContainer.get.isOpen) {
      os.append("In the " + this.getDescriptName() + " is: ")
      os.append( StringHelpers.objectListToStringDescription(this.getContainedObjectsAndPortals(), perspectiveContainer=this, multiline = false)  )
      os.append(".")
    }

    os.toString()
  }

}

class Freezer extends CoolingSource {
  this.name = "freezer"

  this.propCoolingSource = Some(new CoolingSourcePropertiesFreezer)
  this.propCoolingSource.get.setOnMin()
  this.propContainer = Some( new IsContainer() )
  this.propMoveable = Some(new MoveableProperties(isMovable = false))
  this.propDevice = Some(new IsActivableDeviceOn)

  override def tick():Boolean = {
    // If it's activated, then set min temp.  If deactivated, set temp to off.
    if (this.propDevice.isDefined) {
      if (this.propDevice.get.isActivated) {
        this.propCoolingSource.get.setOnMin()
      } else {
        this.propCoolingSource.get.setOff()
      }
    }

    super.tick()
  }

  override def getReferents():Set[String] = {
    Set("freezer", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int):String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName())
    // Only mention being off if it's off, but don't mention being on (since this is assumed).
    if (!this.propDevice.get.isActivated) {
      os.append(", which is turned ")
      if (this.propDevice.get.isActivated) { os.append("on") } else { os.append("off") }
    }
    os.append(". ")

    os.append("The " + this.getDescriptName() + " door is ")
    if (this.propContainer.get.isOpen) {
      os.append("open. ")
    } else {
      os.append("closed. ")
    }

    if (this.propContainer.get.isOpen) {
      os.append("In the " + this.getDescriptName() + " is: ")
      os.append( StringHelpers.objectListToStringDescription(this.getContainedObjectsAndPortals(), perspectiveContainer=this, multiline = false)  )
      os.append(".")
    }

    os.toString()
  }

}

class UltraColdFreezer extends CoolingSource {
  this.name = "ultra low temperature freezer"

  this.propCoolingSource = Some(new CoolingSourcePropertiesULTFreezer)
  this.propCoolingSource.get.setOnMin()
  this.propContainer = Some( new IsContainer() )
  this.propMoveable = Some(new MoveableProperties(isMovable = false))
  this.propDevice = Some(new IsActivableDeviceOn)

  override def tick():Boolean = {
    // If it's activated, then set min temp.  If deactivated, set temp to off.
    if (this.propDevice.isDefined) {
      if (this.propDevice.get.isActivated) {
        this.propCoolingSource.get.setOnMin()
      } else {
        this.propCoolingSource.get.setOff()
      }
    }

    super.tick()
  }

  override def getReferents():Set[String] = {
    Set("freezer", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int):String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName())
    // Only mention being off if it's off, but don't mention being on (since this is assumed).
    if (!this.propDevice.get.isActivated) {
      os.append(", which is turned ")
      if (this.propDevice.get.isActivated) { os.append("on") } else { os.append("off") }
    }
    os.append(". ")

    os.append("The " + this.getDescriptName() + " door is ")
    if (this.propContainer.get.isOpen) {
      os.append("open. ")
    } else {
      os.append("closed. ")
    }

    if (this.propContainer.get.isOpen) {
      os.append("In the " + this.getDescriptName() + " is: ")
      os.append( StringHelpers.objectListToStringDescription(this.getContainedObjectsAndPortals(), perspectiveContainer=this, multiline = false)  )
      os.append(".")
    }

    os.toString()
  }

}
