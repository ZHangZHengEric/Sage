package scienceworld.processes.lifestage

import scienceworld.objects.livingthing.animals.Animal
import scienceworld.objects.livingthing.plant.{Flower, Plant}
import scienceworld.struct.EnvObject


/*
 * Butterfly Life Stages
 */
// Baby stage
class ButterflyLifeStageEgg(obj:Animal, lifecycle:LifeCycle) extends LifeStage(ButterflyLifeStage.BUTTERFLY_STAGE_EGG, obj, lifecycle, canonicalName = "butterfly egg") {
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
      lifecycle.changeStage(ButterflyLifeStage.BUTTERFLY_STAGE_CATERPILLAR)
    }

  }

}

class ButterflyLifeStageCaterpillar(obj:Animal, lifecycle:LifeCycle) extends LifeStage(ButterflyLifeStage.BUTTERFLY_STAGE_CATERPILLAR, obj, lifecycle, canonicalName = "caterpillar") {
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
      lifecycle.changeStage(ButterflyLifeStage.BUTTERFLY_STAGE_PUPA)
    }

  }

}

class ButterflyLifeStagePupa(obj:Animal, lifecycle:LifeCycle) extends LifeStage(ButterflyLifeStage.BUTTERFLY_STAGE_PUPA, obj, lifecycle, canonicalName = "butterfly pupa") {
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
      lifecycle.changeStage(ButterflyLifeStage.BUTTERFLY_STAGE_ADULT)
    }

  }

}


class ButterflyLifeStageAdult(obj:Animal, lifecycle:LifeCycle) extends LifeStage(ButterflyLifeStage.BUTTERFLY_STAGE_ADULT, obj, lifecycle, canonicalName = "adult butterfly") {
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
      lifecycle.changeStage(ButterflyLifeStage.BUTTERFLY_STAGE_DEATH)
    }

  }

}



// Seed stage
class ButterflyLifeStageDeath(obj:Animal, lifecycle:LifeCycle) extends LifeStage(ButterflyLifeStage.BUTTERFLY_STAGE_DEATH, obj, lifecycle, canonicalName = "dead butterfly") {
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


object ButterflyLifeStage {
  // Plant life cycle
  val BUTTERFLY_STAGE_EGG         = "egg"
  val BUTTERFLY_STAGE_CATERPILLAR = "caterpillar"
  val BUTTERFLY_STAGE_PUPA        = "pupa"
  val BUTTERFLY_STAGE_ADULT       = "adult"
  val BUTTERFLY_STAGE_DEATH       = "death"


  // Check to see if a given lifecycle is in the seed stage
  def isEgg(in:LifeCycle):Boolean = {
    if (in.getCurStageName() == BUTTERFLY_STAGE_EGG) return true
    // Otherwise
    return false
  }

  // Make a default plant life cycle
  def mkButterflyLifeCycle(animal:Animal):LifeCycle = {
    val lifecycle = new LifeCycle("butterfly life cycle")

    // TODO
    lifecycle.addStage( new ButterflyLifeStageEgg(animal, lifecycle), isDefault = true )
    lifecycle.addStage( new ButterflyLifeStageCaterpillar(animal, lifecycle) )
    lifecycle.addStage( new ButterflyLifeStagePupa(animal, lifecycle) )
    lifecycle.addStage( new ButterflyLifeStageAdult(animal, lifecycle) )
    lifecycle.addStage( new ButterflyLifeStageDeath(animal, lifecycle) )

    // Return
    lifecycle
  }
}
