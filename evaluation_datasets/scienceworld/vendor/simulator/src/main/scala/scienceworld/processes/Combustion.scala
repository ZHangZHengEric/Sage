package scienceworld.processes

import scienceworld.objects.substance.Ash
import scienceworld.struct.EnvObject

import scala.util.control.Breaks._

object Combustion {
  val COMBUSTION_DELTA_TEMP = 200.0f      // If an object is on fire, it will burn at it's combustion temperature plus this delta

  // Set an object on fire
  def setObjectOnFire(obj:EnvObject): (Boolean, String) = {
    if (obj.propMaterial.isEmpty) return (false, "That is not flammable.")

    if (obj.isOnFire()) return (true, "The " + obj.name + " is already on fire.")

    if (obj.propMaterial.get.combustionTicks > 0) {
      obj.propMaterial.get.isCombusting = true
      obj.propMaterial.get.hasCombusted = true
      return (true, "The " + obj.name + " catches fire.")
    } else {
      return (true, "The " + obj.name + " is not flammable.")
    }
  }

  // Returns the temperature that an object that's on fire will emit (that can set other objects on fire)
  def getBurningTemperature(obj:EnvObject): Double = {
    if (obj.propMaterial.isEmpty) return -273.0f
    return obj.propMaterial.get.combustionPoint + this.COMBUSTION_DELTA_TEMP
  }

  // Put out a fire
  def putOutFire(obj:EnvObject): Unit = {
    if (obj.propMaterial.isEmpty) return
    obj.propMaterial.get.isCombusting = false
    // Should also reduce it's temperature, or it will just start combusting again
    obj.propMaterial.get.temperatureC = obj.propMaterial.get.combustionPoint - 10.0f
  }

  // Main tick for combustion process
  def combustionTick(obj:EnvObject): Unit = {
    // If no material properties, then end
    if (obj.propMaterial.isEmpty) return

    // Step 1: Check to see if the object has exceeded it's combustion temperature, and should combust
    if (obj.propMaterial.get.temperatureC >= obj.propMaterial.get.combustionPoint) {
      if (!obj.isOnFire()) {
        println("### COMBUST (" + obj.name + ") is set ablaze from being above it's combustion point")
        this.setObjectOnFire(obj)
      }
    }

    // Step 2: If on fire, reduce the 'combustionTicks' by one.
    if ((obj.propMaterial.get.isCombusting) && (obj.propMaterial.get.combustionTicks > 0)) {
      println ("### COMBUST (" + obj.name + ") is combusting")
      obj.propMaterial.get.combustionTicks -= 1

      // Set object to a minimum temperature (the combustion point)
      if (obj.propMaterial.get.temperatureC < this.getBurningTemperature(obj)) {
        obj.propMaterial.get.temperatureC = this.getBurningTemperature(obj)
      }

      // Check to see if the object has reached the end of combustion (expired ticks)
      if (obj.propMaterial.get.combustionTicks == 0) {
        // No longer combusting
        obj.propMaterial.get.isCombusting = false

        // Create a combustion product (ash)
        val ash = new Ash()
        ash.propMaterial.get.temperatureC = obj.propMaterial.get.temperatureC       // Inherit temperature

        // Add the combustion product to the container
        val container = obj.getContainer()
        if (container.isDefined) {
          container.get.addObject(ash)
        }

        // Delete the original object
        obj.delete(expelContents = true)

        println("TODO: Combustion of object (" + obj.name + ") has completed.  Replaced with (" + ash.name + ").")

      }

      // Check to see if the object is in the same container as some liquid water (or, the object itself contains water).
      val container = obj.getContainer()
      var objectsThatMightBeWater = obj.getContainedObjects()
      if (container.isDefined) objectsThatMightBeWater ++= container.get.getContainedObjects()

      breakable {
        for (cObj <- objectsThatMightBeWater.toArray.sortBy(_.uuid)) {
          if (cObj.propMaterial.isDefined) {
            if ((cObj.propMaterial.get.substanceName == "water") && (cObj.propMaterial.get.stateOfMatter == "liquid")) {
              println("### COMBUSTION: PUTTING FIRE OUT WITH (" + cObj.name + ").")

              // Turn water into steam (by setting its temperature to be the same as the on-fire-object)
              cObj.propMaterial.get.temperatureC = obj.propMaterial.get.temperatureC

              // Put out fire
              this.putOutFire(obj)

              break()
            }
          }
        }
      }

    }

  }


}
