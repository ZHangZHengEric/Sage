package scienceworld.processes.lifestage

import scienceworld.objects.livingthing.animals.Animal
import scienceworld.struct.EnvObject

/*
 * Adult forever (i.e. no modelled life cycle) Life Stages
 */

class AdultForeverLifeStageAdult(obj:Animal, lifecycle:LifeCycle) extends LifeStage(AdultForeverLifeStage.ADULTFOREVER_STAGE_ADULT, obj, lifecycle, canonicalName = "") {
  var ticksMeetingCriteria:Int = 0
  val stageDuration:Int = 50

  override def tick(): Unit = {
    this.incrementDuration()

    ticksMeetingCriteria += 1
    if (ticksMeetingCriteria >= stageDuration) {

      // Move onto next stage
      //lifecycle.changeStage(TortoiseLifeStage.TORTOISE_STAGE_DEATH)
    }

  }

}

class AdultForeverLifeStageDeath(obj:Animal, lifecycle:LifeCycle) extends LifeStage(TortoiseLifeStage.TORTOISE_STAGE_DEATH, obj, lifecycle, canonicalName = "") {
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


object AdultForeverLifeStage {
  // Plant life cycle
  val ADULTFOREVER_STAGE_ADULT       = "adult"
  val ADULTFOREVER_STAGE_DEATH       = "dead"

  // Check to see if a given lifecycle is in the egg stage
  def isEgg(in:LifeCycle):Boolean = {
    return false
  }

  // Make a default plant life cycle
  def mkAdultForeverLifeCycle(animal:Animal):LifeCycle = {
    val lifecycle = new LifeCycle("adult forever life cycle")

    // TODO
    lifecycle.addStage( new AdultForeverLifeStageAdult(animal, lifecycle), isDefault = true )
    lifecycle.addStage( new AdultForeverLifeStageDeath(animal, lifecycle) )

    // Return
    lifecycle
  }
}
