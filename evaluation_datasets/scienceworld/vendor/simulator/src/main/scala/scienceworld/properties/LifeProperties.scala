package scienceworld.properties

import scienceworld.processes.PlantReproduction

class LifeProperties {
  var lifeformType:String = ""

  // Temperature range -- beyond these ranges, the life form will die
  var minTemp:Double = 0.0
  var maxTemp:Double = 50.0

  // Whether the lifeform is ill or not
  var isSickly:Boolean = false
  var isDead:Boolean = false

  // Typical lifespan (in years) -- note, this does not currently affect the simulation, but is used for question answering.
  var lifespanTypical:Double = 0.0f

  def toJSON():String = {
    val os = new StringBuilder()
    os.append("{")
    os.append("\"lifeformType\": \"" + this.lifeformType + "\",")
    os.append("\"minTemp\":" + this.minTemp + ",")
    os.append("\"maxTemp\":" + this.maxTemp + ",")
    os.append("\"isSickly\":" + this.isSickly + ",")
    os.append("\"isDead\":" + this.isDead + ",")
    os.append("\"lifespanTypical\":" + this.lifespanTypical)
    os.append("}")

    return os.toString()
  }

}


/*
 * Plants
 */

class LifePropertiesPlant extends LifeProperties {
  this.lifeformType = "plant"

  this.minTemp = 0
  this.maxTemp = 50
}


class LifePropertiesApple extends LifePropertiesPlant {
  this.lifeformType = PlantReproduction.PLANT_APPLE
}

class LifePropertiesApricot extends LifePropertiesPlant {
  this.lifeformType = PlantReproduction.PLANT_APRICOT
}

class LifePropertiesAvocado extends LifePropertiesPlant {
  this.lifeformType = PlantReproduction.PLANT_AVOCADO
}

class LifePropertiesBanana extends LifePropertiesPlant {
  this.lifeformType = PlantReproduction.PLANT_BANANA
}

class LifePropertiesCherry extends LifePropertiesPlant {
  this.lifeformType = PlantReproduction.PLANT_CHERRY
}

class LifePropertiesGrapefruit extends LifePropertiesPlant {
  this.lifeformType = PlantReproduction.PLANT_GRAPEFRUIT
}

class LifePropertiesLemon extends LifePropertiesPlant {
  this.lifeformType = PlantReproduction.PLANT_LEMON
}

class LifePropertiesOrange extends LifePropertiesPlant {
  this.lifeformType = PlantReproduction.PLANT_ORANGE
}

class LifePropertiesPeach extends LifePropertiesPlant {
  this.lifeformType = PlantReproduction.PLANT_PEACH
}

class LifePropertiesPear extends LifePropertiesPlant {
  this.lifeformType = PlantReproduction.PLANT_PEAR
}


class LifePropertiesPea extends LifePropertiesPlant {
  this.lifeformType = PlantReproduction.PLANT_PEA
}


class LifePropertiesRandomGeneticsB extends LifePropertiesPlant {
  this.lifeformType = PlantReproduction.PLANT_RANDOMGENETICS_B
}

class LifePropertiesRandomGeneticsC extends LifePropertiesPlant {
  this.lifeformType = PlantReproduction.PLANT_RANDOMGENETICS_C
}

class LifePropertiesRandomGeneticsD extends LifePropertiesPlant {
  this.lifeformType = PlantReproduction.PLANT_RANDOMGENETICS_D
}

class LifePropertiesRandomGeneticsE extends LifePropertiesPlant {
  this.lifeformType = PlantReproduction.PLANT_RANDOMGENETICS_E
}


/*
 * Animals
 */
class LifePropertiesAnimal extends LifeProperties {
  this.lifeformType = "animal"

  this.minTemp = 0
  this.maxTemp = 50

  this.lifespanTypical   = 0.0f   // In years
}

// Long lived
class LifePropertiesGiantTortoise extends LifePropertiesAnimal {
  this.lifeformType         = "giant tortoise"
  this.lifespanTypical      = 150.0f
}

class LifePropertiesElephant extends LifePropertiesAnimal {
  this.lifeformType         = "elephant"
  this.lifespanTypical      = 70.0f
}

class LifePropertiesParrot extends LifePropertiesAnimal {
  this.lifeformType         = "parrot"
  this.lifespanTypical      = 80.0f
}

class LifePropertiesCrocodile extends LifePropertiesAnimal {
  this.lifeformType         = "crocodile"
  this.lifespanTypical      = 45.0f
}

class LifePropertiesBrownBear extends LifePropertiesAnimal {
  this.lifeformType         = "brown bear"
  this.lifespanTypical      = 30.0f
}

// Medium life span

class LifePropertiesBeaver extends LifePropertiesAnimal {
  this.lifeformType         = "beaver"
  this.lifespanTypical      = 16.0f
}

class LifePropertiesWolf extends LifePropertiesAnimal {
  this.lifeformType         = "wolf"
  this.lifespanTypical      = 14.0f
}

class LifePropertiesChipmunk extends LifePropertiesAnimal {
  this.lifeformType         = "chipmunk"
  this.lifespanTypical      = 12.0f
}

class LifePropertiesCommonToad extends LifePropertiesAnimal {
  this.lifeformType         = "common toad"
  this.lifespanTypical      = 10.0f
}

class LifePropertiesRabbit extends LifePropertiesAnimal {
  this.lifeformType         = "rabbit"
  this.lifespanTypical      = 9.0f
}

// Short life span

class LifePropertiesHedgehog extends LifePropertiesAnimal {
  this.lifeformType         = "hedgehog"
  this.lifespanTypical      = 5.0f
}

class LifePropertiesMouse extends LifePropertiesAnimal {
  this.lifeformType         = "mouse"
  this.lifespanTypical      = 4.0f
}

class LifePropertiesChameleon extends LifePropertiesAnimal {
  this.lifeformType         = "chameleon"
  this.lifespanTypical      = 3.0f
}

class LifePropertiesDragonfly extends LifePropertiesAnimal {
  this.lifeformType         = "dragonfly"
  this.lifespanTypical      = 0.4f
}

class LifePropertiesAnt extends LifePropertiesAnimal {
  this.lifeformType         = "ant"
  this.lifespanTypical      = 0.1f
}


// Other
class LifePropertiesButterfly extends LifePropertiesAnimal {
  this.lifeformType         = "butterfly"
  this.lifespanTypical      = 0.1f
}

class LifePropertiesMoth extends LifePropertiesAnimal {
  this.lifeformType         = "moth"
  this.lifespanTypical      = 0.2f
}

class LifePropertiesFrog extends LifePropertiesAnimal {
  this.lifeformType         = "frog"
  this.lifespanTypical      = 6.0f
}

class LifePropertiesDove extends LifePropertiesAnimal {
  this.lifeformType         = "dove"
  this.lifespanTypical      = 2.0f
}

class LifePropertiesBlueJay extends LifePropertiesAnimal {
  this.lifeformType         = "blue jay"
  this.lifespanTypical      = 7.0f
}

class LifePropertiesTurtle extends LifePropertiesAnimal {
  this.lifeformType         = "turtle"
  this.lifespanTypical      = 30.0f
}


class LifePropertiesBee extends LifePropertiesAnimal {
  this.lifeformType         = "bee"
  this.lifespanTypical      = 0.1f
}
