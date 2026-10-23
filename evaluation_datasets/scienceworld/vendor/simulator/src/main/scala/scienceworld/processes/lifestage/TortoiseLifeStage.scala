package scienceworld.processes.lifestage

import scienceworld.objects.livingthing.animals.Animal
import scienceworld.objects.livingthing.plant.{Flower, Plant}
import scienceworld.struct.EnvObject


/*
 * Tortoise Life Stages
 */
// Baby stage
class TortoiseLifeStageEgg(obj:Animal, lifecycle:LifeCycle) extends LifeStage(TortoiseLifeStage.TORTOISE_STAGE_EGG, obj, lifecycle, canonicalName = "") {
  var ticksMeetingCriteria:Int = 0
  val stageDuration:Int = 20

  override def tick(): Unit = {
    this.incrementDuration()

    /*
    // Check to see if the container that the seed is in has water
    val (hasWater, objWater) = this.checkContainerHas("water")
    if (!hasWater) {
      println ("* Plant (" + obj.name + " / " + this.stageName + "): Criteria not met: Missing water")
      return
    }

    // Check to see if the container the seed is in has soil
    val (hasSoil, objSoil) = this.checkContainerHas("soil")
    if (!hasSoil) {
      println ("* Plant (" + obj.name + " / " + this.stageName + "): Criteria not met: Missing soil")
      return
    }
    */

    ticksMeetingCriteria += 1
    if (ticksMeetingCriteria >= stageDuration) {
      /*
      println ("* Plant (" + obj.name + " / " + this.stageName + "): Criteria met: (ticks: " + ticksMeetingCriteria + ")")
      // Consume the water (delete it from the simulation)
      objWater.get.delete()
      */

      // Move onto next stage
      lifecycle.changeStage(TortoiseLifeStage.TORTOISE_STAGE_HATCHLING)
    }

  }

}

class TortoiseLifeStageHatchling(obj:Animal, lifecycle:LifeCycle) extends LifeStage(TortoiseLifeStage.TORTOISE_STAGE_HATCHLING, obj, lifecycle, canonicalName = "") {
  var ticksMeetingCriteria:Int = 0
  val stageDuration:Int = 20

  override def tick(): Unit = {
    this.incrementDuration()

    /*
    // Check to see if the container that the seed is in has water
    val (hasWater, objWater) = this.checkContainerHas("water")
    if (!hasWater) {
      println ("* Plant (" + obj.name + " / " + this.stageName + "): Criteria not met: Missing water")
      return
    }

    // Check to see if the container the seed is in has soil
    val (hasSoil, objSoil) = this.checkContainerHas("soil")
    if (!hasSoil) {
      println ("* Plant (" + obj.name + " / " + this.stageName + "): Criteria not met: Missing soil")
      return
    }
    */

    ticksMeetingCriteria += 1
    if (ticksMeetingCriteria >= stageDuration) {
      /*
      println ("* Plant (" + obj.name + " / " + this.stageName + "): Criteria met: (ticks: " + ticksMeetingCriteria + ")")
      // Consume the water (delete it from the simulation)
      objWater.get.delete()
      */

      // Move onto next stage
      lifecycle.changeStage(TortoiseLifeStage.TORTOISE_STAGE_JUVENILE)
    }

  }

}


class TortoiseLifeStageJuvenile(obj:Animal, lifecycle:LifeCycle) extends LifeStage(TortoiseLifeStage.TORTOISE_STAGE_JUVENILE, obj, lifecycle, canonicalName = "") {
  var ticksMeetingCriteria:Int = 0
  val stageDuration:Int = 20

  override def tick(): Unit = {
    this.incrementDuration()

    /*
    // Check to see if the container that the seed is in has water
    val (hasWater, objWater) = this.checkContainerHas("water")
    if (!hasWater) {
      println ("* Plant (" + obj.name + " / " + this.stageName + "): Criteria not met: Missing water")
      return
    }

    // Check to see if the container the seed is in has soil
    val (hasSoil, objSoil) = this.checkContainerHas("soil")
    if (!hasSoil) {
      println ("* Plant (" + obj.name + " / " + this.stageName + "): Criteria not met: Missing soil")
      return
    }
    */

    ticksMeetingCriteria += 1
    if (ticksMeetingCriteria >= stageDuration) {
      /*
      println ("* Plant (" + obj.name + " / " + this.stageName + "): Criteria met: (ticks: " + ticksMeetingCriteria + ")")
      // Consume the water (delete it from the simulation)
      objWater.get.delete()
      */

      // Move onto next stage
      lifecycle.changeStage(TortoiseLifeStage.TORTOISE_STAGE_ADULT)
    }

  }

}

class TortoiseLifeStageAdult(obj:Animal, lifecycle:LifeCycle) extends LifeStage(TortoiseLifeStage.TORTOISE_STAGE_ADULT, obj, lifecycle, canonicalName = "") {
  var ticksMeetingCriteria:Int = 0
  val stageDuration:Int = 50

  override def tick(): Unit = {
    this.incrementDuration()

    /*
    // Check to see if the container that the seed is in has water
    val (hasWater, objWater) = this.checkContainerHas("water")
    if (!hasWater) {
      println ("* Plant (" + obj.name + " / " + this.stageName + "): Criteria not met: Missing water")
      return
    }

    // Check to see if the container the seed is in has soil
    val (hasSoil, objSoil) = this.checkContainerHas("soil")
    if (!hasSoil) {
      println ("* Plant (" + obj.name + " / " + this.stageName + "): Criteria not met: Missing soil")
      return
    }
    */

    ticksMeetingCriteria += 1
    if (ticksMeetingCriteria >= stageDuration) {
      /*
      println ("* Plant (" + obj.name + " / " + this.stageName + "): Criteria met: (ticks: " + ticksMeetingCriteria + ")")
      // Consume the water (delete it from the simulation)
      objWater.get.delete()
      */

      // Move onto next stage
      lifecycle.changeStage(TortoiseLifeStage.TORTOISE_STAGE_DEATH)
    }

  }

}

class TortoiseLifeStageDeath(obj:Animal, lifecycle:LifeCycle) extends LifeStage(TortoiseLifeStage.TORTOISE_STAGE_DEATH, obj, lifecycle, canonicalName = "") {
  var ticksMeetingCriteria:Int = 0

  override def tick(): Unit = {
    // The animal is dead -- do nothing
    obj.propLife.get.isDead = true

    val parentContainer = obj.getContainer()
    if (parentContainer.isDefined) {
      for (cObj <- obj.getContainedObjectsAndPortals()) {
        cObj match {
          case x:EnvObject => {
            // Catch-all: Whatever the plant contained, move it to the parent container.
            parentContainer.get.addObject(x)
          }
        }

      }
    }

    this.incrementDuration()
  }

}


object TortoiseLifeStage {
  // Plant life cycle
  val TORTOISE_STAGE_EGG         = "egg"
  val TORTOISE_STAGE_HATCHLING   = "hatchling"
  val TORTOISE_STAGE_JUVENILE    = "juvenile"
  val TORTOISE_STAGE_ADULT       = "adult"
  val TORTOISE_STAGE_DEATH       = "dead"


  // Check to see if a given lifecycle is in the seed stage
  def isEgg(in:LifeCycle):Boolean = {
    if (in.getCurStageName() == TORTOISE_STAGE_EGG) return true
    // Otherwise
    return false
  }

  // Make a default plant life cycle
  def mkTortoiseLifeCycle(animal:Animal):LifeCycle = {
    val lifecycle = new LifeCycle("tortoise life cycle")

    // TODO
    lifecycle.addStage( new TortoiseLifeStageEgg(animal, lifecycle), isDefault = true )
    lifecycle.addStage( new TortoiseLifeStageHatchling(animal, lifecycle) )
    lifecycle.addStage( new TortoiseLifeStageJuvenile(animal, lifecycle) )
    lifecycle.addStage( new TortoiseLifeStageAdult(animal, lifecycle) )
    lifecycle.addStage( new TortoiseLifeStageDeath(animal, lifecycle) )

    // Return
    lifecycle
  }
}
