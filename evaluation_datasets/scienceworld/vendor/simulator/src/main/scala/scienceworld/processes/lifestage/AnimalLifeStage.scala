package scienceworld.processes.lifestage

import scienceworld.objects.livingthing.animals.Animal
import scienceworld.objects.livingthing.plant.{Flower, Plant}
import scienceworld.struct.EnvObject

/*
 * Animal Life Stages
 */
// Baby stage
class AnimalLifeStageBaby(obj:Animal, lifecycle:LifeCycle) extends LifeStage(AnimalLifeStage.ANIMAL_STAGE_BABY, obj, lifecycle) {
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
      lifecycle.changeStage(AnimalLifeStage.ANIMAL_STAGE_JUVENILE)
    }

  }

}

class AnimalLifeStageJuvenile(obj:Animal, lifecycle:LifeCycle) extends LifeStage(AnimalLifeStage.ANIMAL_STAGE_JUVENILE, obj, lifecycle) {
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
      lifecycle.changeStage(AnimalLifeStage.ANIMAL_STAGE_ADULT)
    }

  }

}

class AnimalLifeStageAdult(obj:Animal, lifecycle:LifeCycle) extends LifeStage(AnimalLifeStage.ANIMAL_STAGE_ADULT, obj, lifecycle) {
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
      lifecycle.changeStage(AnimalLifeStage.ANIMAL_STAGE_DEATH)
    }

  }

}

// Seed stage
class AnimalLifeStageDeath(obj:Animal, lifecycle:LifeCycle) extends LifeStage(AnimalLifeStage.ANIMAL_STAGE_DEATH, obj, lifecycle) {
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


object AnimalLifeStage {
  // Plant life cycle
  val ANIMAL_STAGE_BABY           = "baby"
  val ANIMAL_STAGE_JUVENILE       = "juvenile"
  val ANIMAL_STAGE_ADULT          = "adult"
  val ANIMAL_STAGE_DEATH          = "dead"


  // Check to see if a given lifecycle is in the seed stage
  def isBaby(in:LifeCycle):Boolean = {
    if (in.getCurStageName() == ANIMAL_STAGE_BABY) return true
    // Otherwise
    return false
  }

  // Make a default plant life cycle
  def mkAnimalLifeCycle(animal:Animal):LifeCycle = {
    val lifecycle = new LifeCycle("animal life cycle")

    // TODO
    lifecycle.addStage( new AnimalLifeStageBaby(animal, lifecycle), isDefault = true )
    lifecycle.addStage( new AnimalLifeStageJuvenile(animal, lifecycle) )
    lifecycle.addStage( new AnimalLifeStageAdult(animal, lifecycle) )
    lifecycle.addStage( new AnimalLifeStageDeath(animal, lifecycle) )

    // Return
    lifecycle
  }
}
