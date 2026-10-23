package scienceworld.processes.lifestage

import scienceworld.objects.livingthing.animals.Animal
import scienceworld.objects.livingthing.plant.{Flower, Plant}
import scienceworld.struct.EnvObject


/*
 * Frog Life Stages
 */
// Baby stage
class FrogLifeStageEgg(obj:Animal, lifecycle:LifeCycle) extends LifeStage(FrogLifeStage.FROG_STAGE_EGG, obj, lifecycle, canonicalName = "frog egg") {
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
      lifecycle.changeStage(FrogLifeStage.FROG_STAGE_TADPOLE)
    }

  }

}

class FrogLifeStageTadpole(obj:Animal, lifecycle:LifeCycle) extends LifeStage(FrogLifeStage.FROG_STAGE_TADPOLE, obj, lifecycle, canonicalName = "tadpole") {
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
      lifecycle.changeStage(FrogLifeStage.FROG_STAGE_ADULT)
    }

  }

}


class FrogLifeStageAdult(obj:Animal, lifecycle:LifeCycle) extends LifeStage(FrogLifeStage.FROG_STAGE_ADULT, obj, lifecycle, canonicalName = "adult frog") {
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
      lifecycle.changeStage(FrogLifeStage.FROG_STAGE_DEATH)
    }

  }

}



class FrogLifeStageDeath(obj:Animal, lifecycle:LifeCycle) extends LifeStage(FrogLifeStage.FROG_STAGE_DEATH, obj, lifecycle, canonicalName = "dead frog") {
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


object FrogLifeStage {
  // Plant life cycle
  val FROG_STAGE_EGG         = "egg"
  val FROG_STAGE_TADPOLE     = "tadpole"
  val FROG_STAGE_ADULT       = "adult"
  val FROG_STAGE_DEATH       = "death"


  // Check to see if a given lifecycle is in the seed stage
  def isEgg(in:LifeCycle):Boolean = {
    if (in.getCurStageName() == FROG_STAGE_EGG) return true
    // Otherwise
    return false
  }

  // Make a default plant life cycle
  def mkFrogLifeCycle(animal:Animal):LifeCycle = {
    val lifecycle = new LifeCycle("frog life cycle")

    // TODO
    lifecycle.addStage( new FrogLifeStageEgg(animal, lifecycle), isDefault = true )
    lifecycle.addStage( new FrogLifeStageTadpole(animal, lifecycle) )
    lifecycle.addStage( new FrogLifeStageAdult(animal, lifecycle) )
    lifecycle.addStage( new FrogLifeStageDeath(animal, lifecycle) )

    // Return
    lifecycle
  }
}
