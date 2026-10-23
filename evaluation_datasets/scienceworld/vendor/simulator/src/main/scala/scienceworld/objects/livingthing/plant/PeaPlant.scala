package scienceworld.objects.livingthing.plant

import scienceworld.processes.genetics.{ChromosomePair, GeneticTrait, GeneticTraitPeas}
import scienceworld.processes.lifestage.PlantLifeStages
import scienceworld.properties.{Edible, LifePropertiesApple, LifePropertiesPea}
import scienceworld.struct.EnvObject.{MODE_CURSORY_DETAIL, MODE_DETAILED}
import util.StringHelpers

import scala.collection.mutable


class PeaPlant(_chromosomePairs:Option[ChromosomePair] = None) extends Tree {
  this.name = "pea"

  this.propEdibility = Some(new Edible())
  propLife = Some(new LifePropertiesPea())
  // Genetics/Chromosomes
  if (this._chromosomePairs == None) {
    this.propChromosomePairs = Some(GeneticTraitPeas.mkRandomChromosomePair())      // Generate Random
  } else {
    this.propChromosomePairs = this._chromosomePairs                                // Defined starting chromosomes
  }


  override def getPlantName():String = {
    // Check if we're in the seed stage
    if (this.isSeed()) {
      // Seed
      val seedName = propLife.get.lifeformType + " seed"
      return this.getDescriptName(seedName)
    } else {
      // Plant in some stage of growth
      val plantName = propLife.get.lifeformType + " plant"
      return this.getDescriptName(plantName)
    }

  }


  override def tick():Boolean = {
    // Update name based on current life stage
    this.name = this.getPlantName()

    // Edibe when in seed form
    if (this.isSeed()) {
      propEdibility.get.isEdible = true
    } else {
      propEdibility.get.isEdible = false
    }

    super.tick()
  }


  override def getReferents(): Set[String] = {
    val plantName = this.getPlantName()

    var out = Set("living thing", "organism", this.name, this.propLife.get.lifeformType, this.name + " in the " + lifecycle.get.getCurStageName() + " stage", lifecycle.get.getCurStageName() + " plant",
      plantName, plantName + " in the " + lifecycle.get.getCurStageName() + " stage", lifecycle.get.getCurStageName() + " " + plantName)

    out ++= Set(this.getDescriptName(), this.getDescriptName() + " in the " + lifecycle.get.getCurStageName() + " stage")

    // Substitute in the genetic trait string to the rest of it
    val out2 = mutable.Set[String]()
    var traitPrefix = this.mkGeneticTraitsStr()
    if (traitPrefix.startsWith(" with a ")) {                       // If the genetic trait prefix starts with " with a ", then trim off " with a "
      traitPrefix = traitPrefix.substring(7).trim()
    }
    if (traitPrefix.length > 0) {
      for (elem <- out) {
        out2 += elem.replaceAll(plantName, traitPrefix.trim() + " " + plantName)
      }
      out ++= out2
    }

    // If ill, append ill referents too
    if (this.propLife.get.isSickly) {
      val sicklyDesc = out.map("sick " + _)
      return out ++ sicklyDesc
    }

    // Return
    out
  }

  // Make PLANT-SPECIFIC (not flower or seed-specific) text to add to the description, based off genetic traits
  override def mkGeneticTraitsStr():String = {
    val os = new StringBuilder()

    if (this.lifecycle.isEmpty) return ""
    if (this.propChromosomePairs.isEmpty) return ""

    // Traits in seed stage
    if (this.lifecycle.get.getCurStageName() == PlantLifeStages.PLANT_STAGE_SEED) {
      os.append(propChromosomePairs.get.getPhenotypeValue(GeneticTrait.TRAIT_SEED_SHAPE).get + " ")
      os.append(propChromosomePairs.get.getPhenotypeValue(GeneticTrait.TRAIT_SEED_COLOR).get + " ")
    }

    // Traits in adult stage
    if ((this.lifecycle.get.getCurStageName() == PlantLifeStages.PLANT_STAGE_ADULT_PLANT) || (this.lifecycle.get.getCurStageName() == PlantLifeStages.PLANT_STAGE_REPRODUCING)) {
      if (propChromosomePairs.isDefined) os.append(" with a " + propChromosomePairs.get.getTraitPhenotypeHumanReadableStr(GeneticTrait.TRAIT_PLANT_HEIGHT).get)
    }

    return os.toString()
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder
    val plantName = this.getPlantName()


    // If dead, simplify the name
    if (propLife.get.isDead) {
      os.append("a dead " + plantName)
      return os.toString()
    }

    // SEED
    if (this.isSeed()) {
      os.append("a " + mkGeneticTraitsStr + " " + plantName)
      if (mode == MODE_DETAILED) {
        // ...
      }
      return os.toString()
    }

    os.append("a " + plantName + " in the " + lifecycle.get.getCurStageName() + " stage")

    // Property: Various genetic traits
    os.append( this.mkGeneticTraitsStr() )

    // Property: Sick
    if (propLife.get.isSickly) os.append(" (that looks unwell)")

    // Property: Contains
    val cObjs = this.getContainedObjectsNotHidden()
    if (cObjs.size > 0) {
      os.append(". ")
      os.append("On the " + plantName + " you see: " + StringHelpers.objectListToStringDescription(cObjs, this, mode = MODE_CURSORY_DETAIL, multiline = false) + ". ")
    }

    if (mode == MODE_DETAILED) {
      // Extended detail
    }

    os.toString
  }


}
