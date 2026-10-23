package scienceworld.objects.taskitems

import scienceworld.objects.substance.Substance
import scienceworld.processes.StateOfMatter
import scienceworld.properties.{MetalProp, WaterProp}
import scienceworld.struct.EnvObject

import scala.util.Random

/*
 * An unknown substance that is either (randomly) electrically conductive or non-conductive.
 */

class UnknownSubstanceElectricalConductivity(letterName:String = "A", isConductive:Boolean) extends EnvObject {
  this.name = "unknown substance " + letterName

  this.propMaterial = Some(new MetalProp)
  this.propMaterial.get.electricallyConductive = isConductive

  override def getReferents(): Set[String] = {
    Set(this.name, "unknown substance", this.getDescriptName())
  }

  override def getDescription(mode: Int): String = {
    return this.name
  }

}


object UnknownSubstanceElectricalConductivity {

  // Make a random substance that is either electrically conductive or non-conductive
  def mkRandomSubstanceElectricalConductive(letterName:String):EnvObject = {
    val randDouble = Random.nextFloat()
    //#val randLetter = (97 + Random.nextInt(25)).toChar.toString

    if (randDouble < 0.50) {
      return new UnknownSubstanceElectricalConductivity(letterName = letterName, isConductive = false)
    } else {
      return new UnknownSubstanceElectricalConductivity(letterName = letterName, isConductive = true)
    }

  }

}

// An unknown substance used for temperature experiments
class UnknownSubstanceThermal(letterName:String = "B") extends EnvObject {
  this.name = "unknown substance " + letterName

  this.propMaterial = Some(new MetalProp)

  override def getReferents(): Set[String] = {
    Set(this.name, "unknown substance", this.getDescriptName())
  }

  override def getDescription(mode: Int): String = {
    return this.name
  }

}

object UnknownSubstanceThermal {

  def mkRandomSubstanceMeltingPoint(letterName:String = "B"):EnvObject = {
    val substance = new UnknownSubstanceThermal(letterName)

    // Melting point
    substance.propMaterial.get.meltingPoint = this.precomputedMeltPoints(letterName)
    substance.propMaterial.get.substanceName = substance.name

    // Names for substance in different states (e.g. solid substance, vs liquid substance)
    val solidName = "solid " + substance.name
    val liquidName = "liquid " + substance.name
    val gasName = "gaseous " + substance.name
    val stateNameMap = Map("solid" -> solidName, "liquid" -> liquidName, "gas" -> gasName)
    substance.propMaterial.get.nameInStateOfMatter = stateNameMap

    // Update the substance name based on it's current temperature/melting point/etc
    StateOfMatter.ChangeOfState(substance, forceNameUpdate = true)

    // Return
    substance
  }

  def precomputedMeltPoints(letterName:String):Double = {
    letterName match {
      case "A" => return 25.0
      case "B" => return 75.0
      case "C" => return 115.0
      case "D" => return -30.0
      case "E" => return -10.0
      case "F" => return 275.0
      case "G" => return 30.0
      case "H" => return 225.0
      case "I" => return 75.0
      case "J" => return -75.0
      case "K" => return 520.0
      case "L" => return 325.0
      case "M" => return -25.0
      case "N" => return 175.0
      case "O" => return 25.0
      case "P" => return 75.0
      case "Q" => return 425.0
      case "R" => return 30.0
      case "S" => return 15.0
      case "T" => return -2.0
      case "U" => return 625.0        // Extreme temperatures
      case "V" => return -220.0
      case "W" => return 575.0
      case "X" => return -175.0
      case "Y" => return 675.0
      case "Z" => return 775.0
      case _ => throw new RuntimeException("ERROR: precomputedMeltPoints(): Unknown letter (" + letterName + ").")
    }
  }

}
