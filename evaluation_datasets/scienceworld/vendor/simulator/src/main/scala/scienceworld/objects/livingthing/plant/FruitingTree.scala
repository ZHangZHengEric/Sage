package scienceworld.objects.livingthing.plant

import scienceworld.objects.livingthing.animals.{Animal, Butterfly}
import scienceworld.processes.lifestage.{ButterflyLifeStage, PlantLifeStages}
import scienceworld.properties.{Edible, LifePropertiesApple, LifePropertiesApricot, LifePropertiesAvocado, LifePropertiesBanana, LifePropertiesCherry, LifePropertiesGrapefruit, LifePropertiesLemon, LifePropertiesOrange, LifePropertiesPeach, LifePropertiesPear}
import scienceworld.struct.EnvObject
import scienceworld.struct.EnvObject.{MODE_CURSORY_DETAIL, MODE_DETAILED}
import util.StringHelpers

import scala.collection.mutable.ArrayBuffer

/*
 * Generic Fruiting Tree
 */
class Tree extends Plant {

}

class FruitingTree extends Tree {
  this.propEdibility = Some(new Edible())

  override def getPlantName():String = {
    // Check if we're in the seed stage
    if (this.isSeed()) {
      // Seed
      val seedName = propLife.get.lifeformType + " seed"
      return this.getDescriptName(seedName)
    } else {
      // Plant in some stage of growth
      val treeName = propLife.get.lifeformType + " tree"
      return this.getDescriptName(treeName)
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

    var out = Set("living thing", "organism", this.name, this.name + " in the " + lifecycle.get.getCurStageName() + " stage", lifecycle.get.getCurStageName() + " plant",
      plantName, plantName + " in the " + lifecycle.get.getCurStageName() + " stage", lifecycle.get.getCurStageName() + " " + plantName)

    out ++= Set(this.getDescriptName(), this.getDescriptName() + " in the " + lifecycle.get.getCurStageName() + " stage")

    // If ill, append ill referents too
    if (this.propLife.get.isSickly) {
      val sicklyDesc = out.map("sick " + _)
      return out ++ sicklyDesc
    }

    // Return
    out
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
      os.append("a " + plantName)
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



/*
 * Specific trees
 */

class AppleTree extends FruitingTree {
  propLife = Some(new LifePropertiesApple())

}

object AppleTree {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = PlantLifeStages.mkPlantLifeCycle(new AppleTree())          //##
    for (lifestage <- lifecycle.stages) {
      val plant = new AppleTree()                                         //##
      plant.lifecycle.get.changeStage(lifestage.stageName)
      out.append(plant)
    }
    out.toArray
  }
}


class AvocadoTree extends FruitingTree {
  propLife = Some(new LifePropertiesAvocado())

}

object AvocadoTree {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = PlantLifeStages.mkPlantLifeCycle(new AppleTree())          //##
    for (lifestage <- lifecycle.stages) {
      val plant = new AvocadoTree()                                         //##
      plant.lifecycle.get.changeStage(lifestage.stageName)
      out.append(plant)
    }
    out.toArray
  }
}


class ApricotTree extends FruitingTree {
  propLife = Some(new LifePropertiesApricot())

}

object ApricotTree {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = PlantLifeStages.mkPlantLifeCycle(new ApricotTree())          //##
    for (lifestage <- lifecycle.stages) {
      val plant = new ApricotTree()                                         //##
      plant.lifecycle.get.changeStage(lifestage.stageName)
      out.append(plant)
    }
    out.toArray
  }
}


class BananaTree extends FruitingTree {
  propLife = Some(new LifePropertiesBanana())

}

object BananaTree {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = PlantLifeStages.mkPlantLifeCycle(new BananaTree())          //##
    for (lifestage <- lifecycle.stages) {
      val plant = new BananaTree()                                         //##
      plant.lifecycle.get.changeStage(lifestage.stageName)
      out.append(plant)
    }
    out.toArray
  }
}


class CherryTree extends FruitingTree {
  propLife = Some(new LifePropertiesCherry())

}

object CherryTree {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = PlantLifeStages.mkPlantLifeCycle(new CherryTree())          //##
    for (lifestage <- lifecycle.stages) {
      val plant = new CherryTree()                                         //##
      plant.lifecycle.get.changeStage(lifestage.stageName)
      out.append(plant)
    }
    out.toArray
  }
}


class GrapefruitTree extends FruitingTree {
  propLife = Some(new LifePropertiesGrapefruit())

}

object GrapefruitTree {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = PlantLifeStages.mkPlantLifeCycle(new GrapefruitTree())          //##
    for (lifestage <- lifecycle.stages) {
      val plant = new GrapefruitTree()                                         //##
      plant.lifecycle.get.changeStage(lifestage.stageName)
      out.append(plant)
    }
    out.toArray
  }
}


class LemonTree extends FruitingTree {
  propLife = Some(new LifePropertiesLemon())

}

object LemonTree {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = PlantLifeStages.mkPlantLifeCycle(new LemonTree())          //##
    for (lifestage <- lifecycle.stages) {
      val plant = new LemonTree()                                         //##
      plant.lifecycle.get.changeStage(lifestage.stageName)
      out.append(plant)
    }
    out.toArray
  }
}


class OrangeTree extends FruitingTree {
  propLife = Some(new LifePropertiesOrange())

}

object OrangeTree {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = PlantLifeStages.mkPlantLifeCycle(new OrangeTree())          //##
    for (lifestage <- lifecycle.stages) {
      val plant = new OrangeTree()                                         //##
      plant.lifecycle.get.changeStage(lifestage.stageName)
      out.append(plant)
    }
    out.toArray
  }
}


class PeachTree extends FruitingTree {
  propLife = Some(new LifePropertiesPeach())
}

object PeachTree {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = PlantLifeStages.mkPlantLifeCycle(new PeachTree())          //##
    for (lifestage <- lifecycle.stages) {
      val plant = new PeachTree()                                         //##
      plant.lifecycle.get.changeStage(lifestage.stageName)
      out.append(plant)
    }
    out.toArray
  }
}


class PearTree extends FruitingTree {
  propLife = Some(new LifePropertiesPear())

}

object PearTree {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = PlantLifeStages.mkPlantLifeCycle(new PearTree())
    for (lifestage <- lifecycle.stages) {
      val plant = new PearTree()
      plant.lifecycle.get.changeStage(lifestage.stageName)
      out.append(plant)
    }
    out.toArray
  }
}
