package scienceworld.objects.livingthing.animals

import scienceworld.objects.livingthing.LivingThing
import scienceworld.processes.lifestage.{AnimalLifeStage, BirdLifeStage, ButterflyLifeStage, FrogLifeStage, TortoiseLifeStage}
import scienceworld.properties.{LifePropertiesAnimal, LifePropertiesAnt, LifePropertiesBeaver, LifePropertiesBlueJay, LifePropertiesBrownBear, LifePropertiesButterfly, LifePropertiesChameleon, LifePropertiesChipmunk, LifePropertiesCommonToad, LifePropertiesCrocodile, LifePropertiesDove, LifePropertiesDragonfly, LifePropertiesElephant, LifePropertiesFrog, LifePropertiesGiantTortoise, LifePropertiesHedgehog, LifePropertiesMoth, LifePropertiesMouse, LifePropertiesParrot, LifePropertiesRabbit, LifePropertiesTurtle, LifePropertiesWolf}
import scienceworld.struct.EnvObject
import scienceworld.struct.EnvObject._
import util.StringHelpers

import scala.collection.mutable.ArrayBuffer

class Animal extends LivingThing {
  this.name = "animal"

  propLife = Some(new LifePropertiesAnimal())

  lifecycle = Some( AnimalLifeStage.mkAnimalLifeCycle(this) )

  override def tick():Boolean = {
    lifecycle.get.tick()

    /*
    var sickly:Boolean = false

    // Check to see if it's out of temperature range -- if so, it dies.
    val temperatureC = this.propMaterial.get.temperatureC
    if ((temperatureC >= this.propLife.get.maxTemp) || (temperatureC <= this.propLife.get.minTemp)) {
      this.propLife.get.durationOutOfTemperatureBounds += 1
      sickly = true
      if (this.propLife.get.durationOutOfTemperatureBounds >= this.propLife.get.maxDurationOutOfTemperatureBounds) {
        lifecycle.get.changeStage(AnimalLifeStage.ANIMAL_STAGE_DEATH)
      }
    } else {
      this.propLife.get.durationOutOfTemperatureBounds = 0
    }



    // Set illness status
    this.propLife.get.isSickly = sickly

    */

    super.tick()
  }

  // Gets the canonical name of the life form, given its current life stage (e.g. baby, adult, etc), handling any special overrides that don't follow regular patterns (e.g. baby butterfly = caterpillar)
  def getCanonicalName():String = {
    // Check to make sure that this life form has a defined life cycle.
    if (lifecycle.isEmpty) return this.name

    // Check for canonical name override
    val curStage = lifecycle.get.getCurStage()
    if (curStage.hasCanonicalName()) {
      return curStage.getCanonicalName()
    }

    // If no canonical name override, default to <stageName> + <lifeformName> pattern
    if (propLife.isEmpty) {
      if (curStage.stageName != "egg") {
        return curStage.stageName + " " + this.name
      } else {
        return this.name + " " + curStage.stageName
      }
    }

    if (curStage.stageName != "egg") {
      return curStage.stageName + " " + propLife.get.lifeformType
    } else {
      return propLife.get.lifeformType + " " + curStage.stageName
    }
  }

  override def getDescriptName(overrideName:String = ""):String = {
    if (overrideName.length > 0) {
      return super.getDescriptName(overrideName)
    } else {
      return super.getDescriptName(this.getCanonicalName())
    }
  }

  override def getReferents(): Set[String] = {
    Set("living thing", "organism", this.name, this.getDescriptName(), lifecycle.get.getCurStageName() + " " + this.name, lifecycle.get.getCurStageName() + " " + this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder

    // If dead, simplify the name
    if (propLife.get.isDead) {
      os.append("a " + this.getDescriptName())
      return os.toString()
    }

    // If alive, give a verbose name
    //os.append("a " + lifecycle.get.getCurStageName() + " " +  this.getDescriptName())
    // This is now all handled in the getCanonicalName()/getDescriptName() functions
    os.append("a " + this.getDescriptName())
    if (propLife.get.isSickly) os.append(" (that looks unwell)")

    /*
    val cObjs = this.getContainedObjectsNotHidden()
    if (cObjs.size > 0) {
      os.append(". ")
      os.append("On it you see: " + StringHelpers.objectListToStringDescription(cObjs, this, mode = MODE_CURSORY_DETAIL, multiline = false) + ". ")
    }
     */

    if (mode == MODE_DETAILED) {
      // Extended detail
    }

    os.toString
  }
}


/*
 * Common animals
 */

class GiantTortoise extends Animal {
  this.name = "giant tortoise"
  this.propLife = Some( new LifePropertiesGiantTortoise() )
  lifecycle = Some( TortoiseLifeStage.mkTortoiseLifeCycle(this) )
}

object GiantTortoise {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = TortoiseLifeStage.mkTortoiseLifeCycle(new Animal)     //##
    for (lifestage <- lifecycle.stages) {
      val animal = new GiantTortoise()                                    //##
      animal.lifecycle.get.changeStage(lifestage.stageName)
      out.append(animal)
    }
    out.toArray
  }
}

class Turtle extends Animal {
  this.name = "turtle"
  this.propLife = Some( new LifePropertiesTurtle() )
  lifecycle = Some( TortoiseLifeStage.mkTortoiseLifeCycle(this) )
}

object Turtle {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = TortoiseLifeStage.mkTortoiseLifeCycle(new Animal)     //##
    for (lifestage <- lifecycle.stages) {
      val animal = new Turtle()                                           //##
      animal.lifecycle.get.changeStage(lifestage.stageName)
      out.append(animal)
    }
    out.toArray
  }
}


class Parrot extends Animal {
  this.name = "parrot"
  this.propLife = Some( new LifePropertiesParrot() )
  lifecycle = Some( BirdLifeStage.mkBirdLifeCycle(this) )
}

object Parrot {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = BirdLifeStage.mkBirdLifeCycle(new Animal)           //##
    for (lifestage <- lifecycle.stages) {
      val animal = new Parrot()                                         //##
      animal.lifecycle.get.changeStage(lifestage.stageName)
      out.append(animal)
    }
    out.toArray
  }
}

class Elephant extends Animal {
  this.name = "elephant"
  this.propLife = Some( new LifePropertiesElephant() )
  lifecycle = Some( AnimalLifeStage.mkAnimalLifeCycle(this) )
}

object Elephant {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = AnimalLifeStage.mkAnimalLifeCycle(new Animal)         //##
    for (lifestage <- lifecycle.stages) {
      val animal = new Elephant()                                         //##
      animal.lifecycle.get.changeStage(lifestage.stageName)
      out.append(animal)
    }
    out.toArray
  }
}

class Crocodile extends Animal {
  this.name = "crocodile"
  this.propLife = Some( new LifePropertiesCrocodile() )
  lifecycle = Some( TortoiseLifeStage.mkTortoiseLifeCycle(this) )
}

object Crocodile {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = TortoiseLifeStage.mkTortoiseLifeCycle(new Animal)      //##
    for (lifestage <- lifecycle.stages) {
      val animal = new Crocodile()                                         //##
      animal.lifecycle.get.changeStage(lifestage.stageName)
      out.append(animal)
    }
    out.toArray
  }
}

class BrownBear extends Animal {
  this.name = "brown bear"
  this.propLife = Some( new LifePropertiesBrownBear() )
  lifecycle = Some( AnimalLifeStage.mkAnimalLifeCycle(this) )
}

object BrownBear {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = AnimalLifeStage.mkAnimalLifeCycle(new Animal)          //##
    for (lifestage <- lifecycle.stages) {
      val animal = new BrownBear()                                         //##
      animal.lifecycle.get.changeStage(lifestage.stageName)
      out.append(animal)
    }
    out.toArray
  }
}

class Beaver extends Animal {
  this.name = "beaver"
  this.propLife = Some( new LifePropertiesBeaver() )
  lifecycle = Some( AnimalLifeStage.mkAnimalLifeCycle(this) )
}

object Beaver {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = AnimalLifeStage.mkAnimalLifeCycle(new Animal)          //##
    for (lifestage <- lifecycle.stages) {
      val animal = new Beaver()                                         //##
      animal.lifecycle.get.changeStage(lifestage.stageName)
      out.append(animal)
    }
    out.toArray
  }
}

class Wolf extends Animal {
  this.name = "wolf"
  this.propLife = Some( new LifePropertiesWolf() )
  lifecycle = Some( AnimalLifeStage.mkAnimalLifeCycle(this) )
}

object Wolf {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = AnimalLifeStage.mkAnimalLifeCycle(new Animal)          //##
    for (lifestage <- lifecycle.stages) {
      val animal = new Wolf()                                         //##
      animal.lifecycle.get.changeStage(lifestage.stageName)
      out.append(animal)
    }
    out.toArray
  }
}

class Chipmunk extends Animal {
  this.name = "chipmunk"
  this.propLife = Some( new LifePropertiesChipmunk() )
  lifecycle = Some( AnimalLifeStage.mkAnimalLifeCycle(this) )
}

class Toad extends Animal {
  this.name = "common toad"
  this.propLife = Some( new LifePropertiesCommonToad() )
  lifecycle = Some( FrogLifeStage.mkFrogLifeCycle(this) )
}

object Toad {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = FrogLifeStage.mkFrogLifeCycle(new Animal)          //##
    for (lifestage <- lifecycle.stages) {
      val animal = new Toad()                                         //##
      animal.lifecycle.get.changeStage(lifestage.stageName)
      out.append(animal)
    }
    out.toArray
  }
}

class Rabbit extends Animal {
  this.name = "rabbit"
  this.propLife = Some( new LifePropertiesRabbit() )
  lifecycle = Some( AnimalLifeStage.mkAnimalLifeCycle(this) )
}


class Mouse extends Animal {
  this.name = "mouse"
  this.propLife = Some( new LifePropertiesMouse() )
  lifecycle = Some( AnimalLifeStage.mkAnimalLifeCycle(this) )
}

class Chameleon extends Animal {
  this.name = "chameleon"
  this.propLife = Some( new LifePropertiesChameleon() )
  lifecycle = Some( TortoiseLifeStage.mkTortoiseLifeCycle(this) )
}

class Dragonfly extends Animal {
  this.name = "dragonfly"
  this.propLife = Some( new LifePropertiesDragonfly() )
  lifecycle = Some( AnimalLifeStage.mkAnimalLifeCycle(this) )     // TODO
}

class Ant extends Animal {
  this.name = "ant"
  this.propLife = Some( new LifePropertiesAnt() )
  lifecycle = Some( AnimalLifeStage.mkAnimalLifeCycle(this) )     // TODO
}

class Hedgehog extends Animal {
  this.name = "hedgehog"
  this.propLife = Some( new LifePropertiesHedgehog() )
  lifecycle = Some( AnimalLifeStage.mkAnimalLifeCycle(this) )
}

/*
 * Animals with detailed life stages
 */
class Butterfly extends Animal {
  this.name = "butterfly"
  this.propLife = Some( new LifePropertiesButterfly() )
  lifecycle = Some( ButterflyLifeStage.mkButterflyLifeCycle(this) )
}

object Butterfly {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = ButterflyLifeStage.mkButterflyLifeCycle(new Animal)          //##
    for (lifestage <- lifecycle.stages) {
      val animal = new Butterfly()                                         //##
      animal.lifecycle.get.changeStage(lifestage.stageName)
      out.append(animal)
    }
    out.toArray
  }
}


class Moth extends Animal {
  this.name = "moth"
  this.propLife = Some( new LifePropertiesMoth() )
  lifecycle = Some( ButterflyLifeStage.mkButterflyLifeCycle(this) )
}

object Moth {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = ButterflyLifeStage.mkButterflyLifeCycle(new Animal)          //##
    for (lifestage <- lifecycle.stages) {
      val animal = new Moth()                                         //##
      animal.lifecycle.get.changeStage(lifestage.stageName)
      out.append(animal)
    }
    out.toArray
  }
}

class Frog extends Animal {
  this.name = "frog"
  this.propLife = Some( new LifePropertiesFrog() )
  lifecycle = Some( FrogLifeStage.mkFrogLifeCycle(this) )
}

object Frog {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = FrogLifeStage.mkFrogLifeCycle(new Animal)          //##
    for (lifestage <- lifecycle.stages) {
      val animal = new Frog()                                         //##
      animal.lifecycle.get.changeStage(lifestage.stageName)
      out.append(animal)
    }
    out.toArray
  }
}

class Dove extends Animal {
  this.name = "dove"
  this.propLife = Some( new LifePropertiesDove() )
  lifecycle = Some( BirdLifeStage.mkBirdLifeCycle(this) )
}

object Dove {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = BirdLifeStage.mkBirdLifeCycle(new Animal)          //##
    for (lifestage <- lifecycle.stages) {
      val animal = new Dove()                                         //##
      animal.lifecycle.get.changeStage(lifestage.stageName)
      out.append(animal)
    }
    out.toArray
  }
}

class BlueJay extends Animal {
  this.name = "blue jay"
  this.propLife = Some( new LifePropertiesBlueJay() )
  lifecycle = Some( BirdLifeStage.mkBirdLifeCycle(this) )
}

object BlueJay {
  // Make instances of this animal at each life stage
  def mkExamplesAtLifeStages():Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]()
    val lifecycle = BirdLifeStage.mkBirdLifeCycle(new Animal)          //##
    for (lifestage <- lifecycle.stages) {
      val animal = new BlueJay()                                         //##
      animal.lifecycle.get.changeStage(lifestage.stageName)
      out.append(animal)
    }
    out.toArray
  }
}
