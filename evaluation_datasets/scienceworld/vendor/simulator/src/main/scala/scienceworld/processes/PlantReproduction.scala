package scienceworld.processes

import scienceworld.objects.livingthing.plant.{AppleTree, ApricotTree, AvocadoTree, BananaTree, CherryTree, GrapefruitTree, LemonTree, OrangeTree, PeaPlant, PeachTree, PearTree, RandomGeneticsPlantsE, RandomGeneticsPlantsB, RandomGeneticsPlantsC, RandomGeneticsPlantsD}
import scienceworld.objects.substance.food.{Apple, Apricot, Avocado, Banana, Cherry, Grapefruit, Lemon, Orange, Peach, Pear}
import scienceworld.processes.genetics.{ChromosomePair, GeneticReproduction}
import scienceworld.struct.EnvObject

class PlantReproduction {

}

object PlantReproduction {
  // Plant names
  val PLANT_APPLE       = "apple"
  val PLANT_APRICOT     = "apricot"
  val PLANT_AVOCADO     = "avocado"
  val PLANT_BANANA      = "banana"
  val PLANT_CHERRY      = "cherry"
  val PLANT_GRAPEFRUIT  = "grapefruit"
  val PLANT_LEMON       = "lemon"
  val PLANT_ORANGE      = "orange"
  val PLANT_PEACH       = "peach"
  val PLANT_PEAR        = "pear"

  val PLANT_PEA         = "pea"

  val PLANT_RANDOMGENETICS_B         = "unknown B"
  val PLANT_RANDOMGENETICS_C         = "unknown C"
  val PLANT_RANDOMGENETICS_D         = "unknown D"
  val PLANT_RANDOMGENETICS_E         = "unknown E"


  // Generator: Create an appropriate fruit for a given plant
  def createFruit(plantType:String, parent1Chromosomes:Option[ChromosomePair], parent2Chromosomes:Option[ChromosomePair]):Option[EnvObject] = {
    // If specified, perform the genetic mating
    var matedChromosomes:Option[ChromosomePair] = None
    if ((parent1Chromosomes.isDefined) && (parent2Chromosomes.isDefined)) {
      matedChromosomes = Some( GeneticReproduction.mateGenesPunnetSquare(parent1Chromosomes.get, parent2Chromosomes.get) )

      println("----------------------------------------")
      println(" MATING CHROMOSOMES:")
      println("----------------------------------------")
      println("Parent 1: ")
      println(parent1Chromosomes.get.toString())
      println("")
      println("Parent 2: ")
      println(parent2Chromosomes.get.toString())
      println("")
      println("Offspring: ")
      println(matedChromosomes.get.toString())
      println("----------------------------------------")
    }

    plantType match {
      case PLANT_APPLE    => { return Some(new Apple())   }
      case PLANT_AVOCADO  => { return Some(new Avocado()) }
      case PLANT_BANANA   => { return Some(new Banana())  }
      case PLANT_CHERRY   => { return Some(new Cherry())  }
      case PLANT_LEMON    => { return Some(new Lemon())   }
      case PLANT_ORANGE   => { return Some(new Orange())  }
      case PLANT_PEACH    => { return Some(new Peach())   }

      case PLANT_APRICOT  => { return Some(new Apricot()) }
      case PLANT_GRAPEFRUIT  => { return Some(new Grapefruit()) }
      case PLANT_PEAR     => { return Some(new Pear()) }


      case PLANT_PEA      => { return Some(new PeaPlant(matedChromosomes))   }

      case PLANT_RANDOMGENETICS_B      => { return Some(new RandomGeneticsPlantsB(matedChromosomes))   }
      case PLANT_RANDOMGENETICS_C      => { return Some(new RandomGeneticsPlantsC(matedChromosomes))   }
      case PLANT_RANDOMGENETICS_D      => { return Some(new RandomGeneticsPlantsD(matedChromosomes))   }
      case PLANT_RANDOMGENETICS_E      => { return Some(new RandomGeneticsPlantsE(matedChromosomes))   }

      case _ => {
        println ("ERROR: Unknown fruit for plant type (" + plantType + "). ")
        return None
      }
    }

  }

  // Generator: Create an appropriate fruit for a given plant
  def createSeed(plantType:String):Option[EnvObject] = {
    plantType match {
      case PLANT_APPLE    => { return Some(new AppleTree())   }
      case PLANT_AVOCADO  => { return Some(new AvocadoTree()) }
      case PLANT_BANANA   => { return Some(new BananaTree())  }
      case PLANT_CHERRY   => { return Some(new CherryTree())  }
      case PLANT_LEMON    => { return Some(new LemonTree())   }
      case PLANT_ORANGE   => { return Some(new OrangeTree())  }
      case PLANT_PEACH    => { return Some(new PeachTree())   }

      case PLANT_APRICOT    => { return Some(new ApricotTree())   }
      case PLANT_GRAPEFRUIT    => { return Some(new GrapefruitTree())   }
      case PLANT_PEAR     => { return Some(new PearTree())   }

      case PLANT_PEA      => { return Some(new PeaPlant())    }

      case PLANT_RANDOMGENETICS_B      => { return Some(new RandomGeneticsPlantsB())    }
      case PLANT_RANDOMGENETICS_C      => { return Some(new RandomGeneticsPlantsC())    }
      case PLANT_RANDOMGENETICS_D      => { return Some(new RandomGeneticsPlantsD())    }
      case PLANT_RANDOMGENETICS_E      => { return Some(new RandomGeneticsPlantsE())    }

      case _ => {
        println ("ERROR: Unknown seed for plant type (" + plantType + "). ")
        return None
      }
    }

  }

}
