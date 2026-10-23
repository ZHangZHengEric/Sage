package scienceworld.objects.devices

import scienceworld.objects.portal.LiquidDrain
import scienceworld.objects.substance.Water
import scienceworld.properties.{CeramicProp, IsActivableDeviceOff, IsOpenUnclosableContainer, MoveableProperties, SteelProp}
import scienceworld.struct.EnvObject
import scienceworld.struct.EnvObject._
import util.StringHelpers

/*
 * Sink
 */
class Sink(drainsTo:Option[EnvObject]) extends Device {
  this.name = "sink"

  this.propMaterial = Some(new SteelProp())
  this.propContainer = Some( new IsOpenUnclosableContainer() )
  this.propDevice = Some(new IsActivableDeviceOff())
  this.propMoveable = Some(new MoveableProperties(isMovable = false))

  // Include a drain in the sink
  if (drainsTo.isDefined) {
    val drain = new LiquidDrain(isOpen = true, connectsFrom = this, connectsTo = drainsTo.get)
    this.addPortal(drain)
  }


  override def tick():Boolean = {
    // If sink is activated, put water into containers inside it
    if (this.propDevice.get.isActivated) {

      // Step 1: Put water into any containers inside the sink
      for (obj <- this.getContainedObjects()) {
        if ((obj.propContainer.isDefined) && (obj.propContainer.get.isContainer)) {
          // The object is a container -- check to see if it's open
          if (obj.propContainer.get.isOpen) {
            // The object is open -- check to see if it already contains water
            val existingWater = obj.getContainedObjectsOfType[Water]()
            if (existingWater.size == 0) {
              // Add new water
              obj.addObject( new Water() )
            }
          }

        }
      }

      // Step 2: Put water into the sink itself
      val existingWater = this.getContainedObjectsOfType[Water]()
      if (existingWater.size == 0) {
        // Add new water
        this.addObject( new Water() )
      }


      // TODO: Make objects wet?
      // TODO: Objects that react with water? (e.g. paper?)

    }

    super.tick()
  }

  override def getReferents(): Set[String] = {
    Set("sink", this.name, this.getDescriptName())
  }

  override def getDescription(mode: Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + ", which is turned ")
    if (this.propDevice.get.isActivated) {
      os.append("on")
    } else {
      os.append("off")
    }
    os.append(". ")
    os.append("In the " + this.getDescriptName() + " is: ")
    os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = false)  )
    os.append(".")

    if (mode == MODE_DETAILED) {
      val portals = this.getPortals()
      if (this.getPortals().size > 0) {
        for (portal <- portals) {
          os.append(" The " + portal.name + " is " + portal.getOpenClosedStr() + ".")
        }
      }
    }

    os.toString
  }
}


/*
 * Bath tub
 */
class Bathtub(drainsTo:Option[EnvObject]) extends Device {
  this.name = "bathtub"

  this.propMaterial = Some(new CeramicProp())
  this.propContainer = Some( new IsOpenUnclosableContainer() )
  this.propDevice = Some(new IsActivableDeviceOff())
  this.propMoveable = Some(new MoveableProperties(isMovable = false))

  // Include a drain in the sink
  if (drainsTo.isDefined) {
    val drain = new LiquidDrain(isOpen = true, connectsFrom = this, connectsTo = drainsTo.get)
    this.addPortal(drain)
  }


  override def tick():Boolean = {
    // If sink is activated, put water into containers inside it
    if (this.propDevice.get.isActivated) {

      // Step 1: Put water into any containers inside the bath
      for (obj <- this.getContainedObjects()) {
        if ((obj.propContainer.isDefined) && (obj.propContainer.get.isContainer)) {
          // The object is a container -- check to see if it's open
          if (obj.propContainer.get.isOpen) {
            // The object is open -- check to see if it already contains water
            val existingWater = obj.getContainedObjectsOfType[Water]()
            if (existingWater.size == 0) {
              // Add new water
              obj.addObject( new Water() )
            }
          }

        }
      }

      // Step 2: Put water into the bath itself
      val existingWater = this.getContainedObjectsOfType[Water]()
      if (existingWater.size == 0) {
        // Add new water
        this.addObject( new Water() )
      }


      // TODO: Make objects wet?
      // TODO: Objects that react with water? (e.g. paper?)

    }

    super.tick()
  }

  override def getReferents(): Set[String] = {
    Set("bathtub", this.name, this.getDescriptName())
  }

  override def getDescription(mode: Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + ", which is turned ")
    if (this.propDevice.get.isActivated) {
      os.append("on")
    } else {
      os.append("off")
    }
    os.append(". ")
    os.append("In the " + this.getDescriptName() + " is: ")
    os.append( StringHelpers.objectListToStringDescription(this.getContainedObjects(), perspectiveContainer=this, multiline = false)  )
    os.append(".")

    if (mode == MODE_DETAILED) {
      val portals = this.getPortals()
      if (this.getPortals().size > 0) {
        for (portal <- portals) {
          os.append(" The " + portal.name + " is " + portal.getOpenClosedStr() + ".")
        }
      }
    }

    os.toString
  }
}


/*
 * Toilet
 */
class Toilet(drainsTo:EnvObject) extends Device {
  this.name = "toilet"

  this.propMaterial = Some(new SteelProp())
  this.propContainer = Some( new IsOpenUnclosableContainer() )
  this.propDevice = Some(new IsActivableDeviceOff())
  this.propMoveable = Some(new MoveableProperties(isMovable = false))

  // Include a drain in the toilet
  val drain = new LiquidDrain(isOpen = true, connectsFrom = this, connectsTo = drainsTo)
  this.addPortal(drain)

  // Initialize toilet
  var toiletFlushStage:Int = 0
  this.addObject( new Water() )   // Add water to the bowl



  override def tick():Boolean = {

    // Activate flush
    if (this.propDevice.get.isActivated && this.toiletFlushStage == 0) {
      this.toiletFlushStage = 1
      drain.propPortal.get.isOpen = true
    }

    // Flush
    if (this.toiletFlushStage > 0) {
      // Step 1: Put water into any containers inside the toilet
      for (obj <- this.getContainedObjects()) {
        if ((obj.propContainer.isDefined) && (obj.propContainer.get.isContainer)) {
          // The object is a container -- check to see if it's open
          if (obj.propContainer.get.isOpen) {
            // The object is open -- check to see if it already contains water
            val existingWater = obj.getContainedObjectsOfType[Water]()
            if (existingWater.size == 0) {
              // Add new water
              obj.addObject( new Water() )
            }
          }
        }
      }

      // Step 2: Put water into the toilet itself
      val existingWater = this.getContainedObjectsOfType[Water]()
      if (existingWater.size == 0) {
        // Add new water
        this.addObject( new Water() )
      }

      // Increment toilet flush stage
      this.toiletFlushStage += 1

      // Stop flushing after 5 counts of 'flushing'
      if (this.toiletFlushStage > 5) {
        this.propDevice.get.isActivated = false
        this.toiletFlushStage = 0
      }
    }

    // Seal drain if not flushing
    if (this.toiletFlushStage == 0) {
      drain.propPortal.get.isOpen = false
    }

    super.tick()
  }


  override def getReferents(): Set[String] = {
    Set("toilet", this.name, this.getDescriptName())
  }

  override def getDescription(mode: Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName())
    if (this.toiletFlushStage > 0) os.append(", which is flushing")
    os.append(". ")

    if (this.getContainedObjects().size > 0) {
      os.append("In the " + this.getDescriptName() + " is: ")
      os.append( StringHelpers.objectListToStringDescription(this.getContainedObjectsAndPortals(), perspectiveContainer=this, multiline = false)  )
      os.append(".")
    }

    os.toString
  }
}
