package scienceworld.processes.genetics

import scienceworld.processes.genetics.GeneticTrait._

import scala.collection.mutable.ArrayBuffer


/*
 * Random (unknown) plants
 */

object GeneticTraitUnknownPlantE {

  def mkTraitSeedColor(dominantOrRecessive:String):GeneticTrait = {
    new GeneticTrait(TRAIT_SEED_COLOR, valueDominant = "blue", valueRecessive = "brown", strSuffix = "seed", dominantOrRecessive)
  }

  def mkTraitSeedShape(dominantOrRecessive:String):GeneticTrait = {
    new GeneticTrait(TRAIT_SEED_SHAPE, valueDominant = "round", valueRecessive = "square", strSuffix = "seed", dominantOrRecessive)
  }

  def mkTraitLeafShape(dominantOrRecessive:String):GeneticTrait = {
    new GeneticTrait(TRAIT_LEAF_SHAPE, valueDominant = "elliptical", valueRecessive = "linear", strSuffix = "leaves", dominantOrRecessive)
  }

  def mkTraitFlowerSize(dominantOrRecessive:String):GeneticTrait = {
    new GeneticTrait(TRAIT_FLOWER_SIZE, valueDominant = "small", valueRecessive = "large", strSuffix = "flowers", dominantOrRecessive)
  }


  /*
   * Make random traits
   */
  def mkRandomChromosomePair():ChromosomePair = {
    val parent1 = new Chromosomes( this.mkRandomTraits() )
    val parent2 = new Chromosomes( this.mkRandomTraits() )
    return new ChromosomePair(parent1, parent2)
  }

  def mkRandomTraits():Array[GeneticTrait] = {
    val out = new ArrayBuffer[GeneticTrait]()

    out.append( mkTraitSeedColor(GeneticTrait.mkRandomDomRec()) )
    out.append( mkTraitSeedShape(GeneticTrait.mkRandomDomRec()) )
    out.append( mkTraitLeafShape(GeneticTrait.mkRandomDomRec()) )
    out.append( mkTraitFlowerSize(GeneticTrait.mkRandomDomRec()) )

    // Return
    out.toArray
  }

  /*
   * Make random traits (but, control one trait)
   */
  def mkRandomChromosomePairExcept(traitName:String, parent1DomOrRec:String, parent2DomOrRec:String):ChromosomePair = {
    val parent1 = new Chromosomes( this.mkRandomTraitsExcept(traitName, parent1DomOrRec) )
    val parent2 = new Chromosomes( this.mkRandomTraitsExcept(traitName, parent2DomOrRec) )
    return new ChromosomePair(parent1, parent2)
  }

  def mkRandomTraitsExcept(traitName:String, domOrRec:String):Array[GeneticTrait] = {
    val out = new ArrayBuffer[GeneticTrait]()

    if (traitName == TRAIT_SEED_COLOR) {
      out.append(mkTraitSeedColor(domOrRec))
    } else {
      out.append(mkTraitSeedColor(GeneticTrait.mkRandomDomRec()))
    }

    if (traitName == TRAIT_LEAF_SHAPE) {
      out.append(mkTraitLeafShape(domOrRec))
    } else {
      out.append(mkTraitLeafShape(GeneticTrait.mkRandomDomRec()))
    }

    if (traitName == TRAIT_FLOWER_SIZE) {
      out.append(mkTraitFlowerSize(domOrRec))
    } else {
      out.append(mkTraitFlowerSize(GeneticTrait.mkRandomDomRec()))
    }

    if (traitName == TRAIT_SEED_SHAPE) {
      out.append(mkTraitSeedShape(domOrRec))
    } else {
      out.append(mkTraitSeedShape(GeneticTrait.mkRandomDomRec()))
    }

    // Return
    out.toArray
  }

}



object GeneticTraitUnknownPlantB {

  def mkTraitPlantHeight(dominantOrRecessive:String):GeneticTrait = {
    new GeneticTrait(TRAIT_PLANT_HEIGHT, valueDominant = "short", valueRecessive = "tall", strSuffix = "height", dominantOrRecessive)
  }

  def mkTraitSeedColor(dominantOrRecessive:String):GeneticTrait = {
    new GeneticTrait(TRAIT_SEED_COLOR, valueDominant = "green", valueRecessive = "yellow", strSuffix = "seed", dominantOrRecessive)
  }

  def mkTraitFlowerSize(dominantOrRecessive:String):GeneticTrait = {
    new GeneticTrait(TRAIT_FLOWER_SIZE, valueDominant = "large", valueRecessive = "small", strSuffix = "flowers", dominantOrRecessive)
  }

  def mkTraitFlowerColor(dominantOrRecessive:String):GeneticTrait = {
    new GeneticTrait(TRAIT_FLOWER_COLOR, valueDominant = "orange", valueRecessive = "yellow", strSuffix = "flowers", dominantOrRecessive)
  }


  /*
   * Make random traits
   */
  def mkRandomChromosomePair():ChromosomePair = {
    val parent1 = new Chromosomes( this.mkRandomTraits() )
    val parent2 = new Chromosomes( this.mkRandomTraits() )
    return new ChromosomePair(parent1, parent2)
  }

  def mkRandomTraits():Array[GeneticTrait] = {
    val out = new ArrayBuffer[GeneticTrait]()

    out.append( mkTraitPlantHeight(GeneticTrait.mkRandomDomRec()) )
    out.append( mkTraitSeedColor(GeneticTrait.mkRandomDomRec()) )
    out.append( mkTraitFlowerSize(GeneticTrait.mkRandomDomRec()) )
    out.append( mkTraitFlowerColor(GeneticTrait.mkRandomDomRec()) )

    // Return
    out.toArray
  }

  /*
   * Make random traits (but, control one trait)
   */
  def mkRandomChromosomePairExcept(traitName:String, parent1DomOrRec:String, parent2DomOrRec:String):ChromosomePair = {
    val parent1 = new Chromosomes( this.mkRandomTraitsExcept(traitName, parent1DomOrRec) )
    val parent2 = new Chromosomes( this.mkRandomTraitsExcept(traitName, parent2DomOrRec) )
    return new ChromosomePair(parent1, parent2)
  }

  def mkRandomTraitsExcept(traitName:String, domOrRec:String):Array[GeneticTrait] = {
    val out = new ArrayBuffer[GeneticTrait]()

    if (traitName == TRAIT_PLANT_HEIGHT) {
      out.append(mkTraitPlantHeight(domOrRec))
    } else {
      out.append(mkTraitPlantHeight(GeneticTrait.mkRandomDomRec()))
    }

    if (traitName == TRAIT_SEED_COLOR) {
      out.append(mkTraitSeedColor(domOrRec))
    } else {
      out.append(mkTraitSeedColor(GeneticTrait.mkRandomDomRec()))
    }

    if (traitName == TRAIT_FLOWER_SIZE) {
      out.append(mkTraitFlowerSize(domOrRec))
    } else {
      out.append(mkTraitFlowerSize(GeneticTrait.mkRandomDomRec()))
    }

    if (traitName == TRAIT_FLOWER_COLOR) {
      out.append(mkTraitFlowerColor(domOrRec))
    } else {
      out.append(mkTraitFlowerColor(GeneticTrait.mkRandomDomRec()))
    }

    // Return
    out.toArray
  }

}

object GeneticTraitUnknownPlantC {

  def mkTraitPlantHeight(dominantOrRecessive:String):GeneticTrait = {
    new GeneticTrait(TRAIT_PLANT_HEIGHT, valueDominant = "short", valueRecessive = "tall", strSuffix = "height", dominantOrRecessive)
  }

  def mkTraitLeafShape(dominantOrRecessive:String):GeneticTrait = {
    new GeneticTrait(TRAIT_LEAF_SHAPE, valueDominant = "pointed", valueRecessive = "round", strSuffix = "leaves", dominantOrRecessive)
  }

  def mkTraitFlowerSize(dominantOrRecessive:String):GeneticTrait = {
    new GeneticTrait(TRAIT_FLOWER_SIZE, valueDominant = "large", valueRecessive = "small", strSuffix = "flowers", dominantOrRecessive)
  }

  def mkTraitFlowerColor(dominantOrRecessive:String):GeneticTrait = {
    new GeneticTrait(TRAIT_FLOWER_COLOR, valueDominant = "orange", valueRecessive = "yellow", strSuffix = "flowers", dominantOrRecessive)
  }


  /*
   * Make random traits
   */
  def mkRandomChromosomePair():ChromosomePair = {
    val parent1 = new Chromosomes( this.mkRandomTraits() )
    val parent2 = new Chromosomes( this.mkRandomTraits() )
    return new ChromosomePair(parent1, parent2)
  }

  def mkRandomTraits():Array[GeneticTrait] = {
    val out = new ArrayBuffer[GeneticTrait]()

    out.append( mkTraitPlantHeight(GeneticTrait.mkRandomDomRec()) )
    out.append( mkTraitLeafShape(GeneticTrait.mkRandomDomRec()) )
    out.append( mkTraitFlowerSize(GeneticTrait.mkRandomDomRec()) )
    out.append( mkTraitFlowerColor(GeneticTrait.mkRandomDomRec()) )

    // Return
    out.toArray
  }

  /*
   * Make random traits (but, control one trait)
   */
  def mkRandomChromosomePairExcept(traitName:String, parent1DomOrRec:String, parent2DomOrRec:String):ChromosomePair = {
    val parent1 = new Chromosomes( this.mkRandomTraitsExcept(traitName, parent1DomOrRec) )
    val parent2 = new Chromosomes( this.mkRandomTraitsExcept(traitName, parent2DomOrRec) )
    return new ChromosomePair(parent1, parent2)
  }

  def mkRandomTraitsExcept(traitName:String, domOrRec:String):Array[GeneticTrait] = {
    val out = new ArrayBuffer[GeneticTrait]()

    if (traitName == TRAIT_PLANT_HEIGHT) {
      out.append(mkTraitPlantHeight(domOrRec))
    } else {
      out.append(mkTraitPlantHeight(GeneticTrait.mkRandomDomRec()))
    }

    if (traitName == TRAIT_LEAF_SHAPE) {
      out.append(mkTraitLeafShape(domOrRec))
    } else {
      out.append(mkTraitLeafShape(GeneticTrait.mkRandomDomRec()))
    }

    if (traitName == TRAIT_FLOWER_SIZE) {
      out.append(mkTraitFlowerSize(domOrRec))
    } else {
      out.append(mkTraitFlowerSize(GeneticTrait.mkRandomDomRec()))
    }

    if (traitName == TRAIT_FLOWER_COLOR) {
      out.append(mkTraitFlowerColor(domOrRec))
    } else {
      out.append(mkTraitFlowerColor(GeneticTrait.mkRandomDomRec()))
    }

    // Return
    out.toArray
  }

}


object GeneticTraitUnknownPlantD {

  def mkTraitSeedShape(dominantOrRecessive:String):GeneticTrait = {
    new GeneticTrait(TRAIT_SEED_SHAPE, valueDominant = "spherical", valueRecessive = "ovate", strSuffix = "seed", dominantOrRecessive)
  }

  def mkTraitLeafSize(dominantOrRecessive:String):GeneticTrait = {
    new GeneticTrait(TRAIT_LEAF_SIZE, valueDominant = "medium", valueRecessive = "large", strSuffix = "leaves", dominantOrRecessive)
  }

  def mkTraitFlowerSize(dominantOrRecessive:String):GeneticTrait = {
    new GeneticTrait(TRAIT_FLOWER_SIZE, valueDominant = "small", valueRecessive = "medium", strSuffix = "flowers", dominantOrRecessive)
  }

  def mkTraitFlowerColor(dominantOrRecessive:String):GeneticTrait = {
    new GeneticTrait(TRAIT_FLOWER_COLOR, valueDominant = "blue", valueRecessive = "red", strSuffix = "flowers", dominantOrRecessive)
  }


  /*
   * Make random traits
   */
  def mkRandomChromosomePair():ChromosomePair = {
    val parent1 = new Chromosomes( this.mkRandomTraits() )
    val parent2 = new Chromosomes( this.mkRandomTraits() )
    return new ChromosomePair(parent1, parent2)
  }

  def mkRandomTraits():Array[GeneticTrait] = {
    val out = new ArrayBuffer[GeneticTrait]()

    out.append( mkTraitSeedShape(GeneticTrait.mkRandomDomRec()) )
    out.append( mkTraitLeafSize(GeneticTrait.mkRandomDomRec()) )
    out.append( mkTraitFlowerSize(GeneticTrait.mkRandomDomRec()) )
    out.append( mkTraitFlowerColor(GeneticTrait.mkRandomDomRec()) )

    // Return
    out.toArray
  }

  /*
   * Make random traits (but, control one trait)
   */
  def mkRandomChromosomePairExcept(traitName:String, parent1DomOrRec:String, parent2DomOrRec:String):ChromosomePair = {
    val parent1 = new Chromosomes( this.mkRandomTraitsExcept(traitName, parent1DomOrRec) )
    val parent2 = new Chromosomes( this.mkRandomTraitsExcept(traitName, parent2DomOrRec) )
    return new ChromosomePair(parent1, parent2)
  }

  def mkRandomTraitsExcept(traitName:String, domOrRec:String):Array[GeneticTrait] = {
    val out = new ArrayBuffer[GeneticTrait]()

    if (traitName == TRAIT_SEED_SHAPE) {
      out.append(mkTraitSeedShape(domOrRec))
    } else {
      out.append(mkTraitSeedShape(GeneticTrait.mkRandomDomRec()))
    }

    if (traitName == TRAIT_LEAF_SIZE) {
      out.append(mkTraitLeafSize(domOrRec))
    } else {
      out.append(mkTraitLeafSize(GeneticTrait.mkRandomDomRec()))
    }

    if (traitName == TRAIT_FLOWER_SIZE) {
      out.append(mkTraitFlowerSize(domOrRec))
    } else {
      out.append(mkTraitFlowerSize(GeneticTrait.mkRandomDomRec()))
    }

    if (traitName == TRAIT_FLOWER_COLOR) {
      out.append(mkTraitFlowerColor(domOrRec))
    } else {
      out.append(mkTraitFlowerColor(GeneticTrait.mkRandomDomRec()))
    }

    // Return
    out.toArray
  }

}
