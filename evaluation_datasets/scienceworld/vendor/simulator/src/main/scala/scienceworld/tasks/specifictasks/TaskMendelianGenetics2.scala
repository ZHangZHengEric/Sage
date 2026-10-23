package scienceworld.tasks.specifictasks

import scienceworld.objects.agent.Agent
import scienceworld.objects.containers.{CeramicCup, FlowerPot, Jug, SelfWateringFlowerPot}
import scienceworld.objects.livingthing.plant.{PeaPlant, Plant, RandomGeneticsPlants, RandomGeneticsPlantsE, RandomGeneticsPlantsB, RandomGeneticsPlantsC, RandomGeneticsPlantsD, Soil}
import scienceworld.objects.taskitems.AnswerBox
import scienceworld.processes.genetics.{Chromosomes, GeneticTrait, GeneticTraitPeas, GeneticTraitUnknownPlantE, GeneticTraitUnknownPlantB, GeneticTraitUnknownPlantC, GeneticTraitUnknownPlantD}
import scienceworld.struct.EnvObject
import scienceworld.tasks.{Task, TaskMaker1, TaskModifier, TaskObject, TaskValueStr}
import scienceworld.tasks.goals.{Goal, GoalSequence}
import scienceworld.tasks.goals.specificgoals.{GoalContainerOpen, GoalFind, GoalInRoomWithObject, GoalLifeStageAnywhere, GoalMoveToLocation, GoalMoveToNewLocation, GoalSpecificObjectInDirectContainer}
import TaskMendelianGenetics2._
import scienceworld.actions.Action
import scienceworld.goldagent.PathFinder
import scienceworld.objects.containers.furniture.BeeHive
import scienceworld.objects.devices.{Shovel, Sink}
import scienceworld.objects.livingthing.LivingThing
import scienceworld.processes.PlantReproduction
import scienceworld.processes.lifestage.PlantLifeStages.{PLANT_STAGE_ADULT_PLANT, PLANT_STAGE_REPRODUCING, PLANT_STAGE_SEED, PLANT_STAGE_SEEDLING}
import scienceworld.runtime.pythonapi.PythonInterface

import scala.collection.mutable.ArrayBuffer
import scala.util.Random
import scala.util.control.Breaks.{break, breakable}


class TaskMendelianGenetics2(val mode:String = MODE_MENDEL_UNKNOWN) extends TaskParametric {
  val taskName = mode.replaceAll(" ", "-").replaceAll("[()]", "")

  val locations = Array("greenhouse")

  // Variation 1: Genetic Trait
  val genetics = new ArrayBuffer[ Array[TaskModifier] ]()

  // Generate a random set of traits, just to determine which are dominant/recessive.

  val maxUnknownPlants = 4

  for (location <- locations) {

    // Cycle through unknown/random plants (e.g. randomPlantA, randomPlantB, randomPlantC, etc).
    for (plantIdx <- 0 until maxUnknownPlants) {
      var traits:Chromosomes = null
      var traitNames:Array[String] = null
      var plantName:String = ""
      var seedType:String = ""

      if (plantIdx == 0) {
        traits = new Chromosomes(GeneticTraitUnknownPlantE.mkRandomTraits()) // Make a random instance of the plant, just to get the genetic trait names
        traitNames = traits.getTraitNames()
        plantName = new RandomGeneticsPlantsE().name + " plant"
        seedType = new RandomGeneticsPlantsE().propLife.get.lifeformType
      } else if (plantIdx == 1) {
        traits = new Chromosomes(GeneticTraitUnknownPlantB.mkRandomTraits()) // Make a random instance of the plant, just to get the genetic trait names
        traitNames = traits.getTraitNames()
        plantName = new RandomGeneticsPlantsB().name + " plant"
        seedType = new RandomGeneticsPlantsB().propLife.get.lifeformType
      } else if (plantIdx == 2) {
        traits = new Chromosomes(GeneticTraitUnknownPlantC.mkRandomTraits()) // Make a random instance of the plant, just to get the genetic trait names
        traitNames = traits.getTraitNames()
        plantName = new RandomGeneticsPlantsC().name + " plant"
        seedType = new RandomGeneticsPlantsC().propLife.get.lifeformType
      } else if (plantIdx == 3) {
        traits = new Chromosomes(GeneticTraitUnknownPlantD.mkRandomTraits()) // Make a random instance of the plant, just to get the genetic trait names
        traitNames = traits.getTraitNames()
        plantName = new RandomGeneticsPlantsD().name + " plant"
        seedType = new RandomGeneticsPlantsD().propLife.get.lifeformType
      } else {
        throw new RuntimeException("ERROR: Unknown plantIdx (" + plantIdx + ")")
      }

      // Cycle through all the genetic traits in the random plant
      for (traitName <- traitNames) {
        for (domOrRec <- Array(GeneticTrait.DOMINANT, GeneticTrait.RECESSIVE)) {
          var specificTraitValue = ""
          if (domOrRec == GeneticTrait.DOMINANT) {
            specificTraitValue = traits.getTrait(traitName).get.valueDominant
          } else {
            specificTraitValue = traits.getTrait(traitName).get.valueRecessive
          }

          val seedJar = TaskMendelianGenetics2.mkUnknownPlantSeedJar(plantIdx, traitName)

          genetics.append(Array(new TaskObject(seedJar.name, Some(seedJar), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
            new TaskValueStr(key = "domOrRec", value = domOrRec),
            new TaskValueStr(key = "traitName", value = traitName),
            new TaskValueStr(key = "traitValue", value = specificTraitValue),
            new TaskValueStr(key = "plantName", value = plantName),
            new TaskValueStr(key = "seedType", value = seedType)
          ))

        }
      }

    }

  }

  // Variation 2: Flower pot names
  val flowerpots = new ArrayBuffer[ Array[TaskModifier] ]()
  for (location <- locations) {

    for (i <- 0 until 5) {      // 5 different variations of pot names
      val out = new ArrayBuffer[TaskModifier]()
      val pots = TaskMendelianGenetics2.mkFlowerPots(numPots = 6)
      val potNames = new ArrayBuffer[String]
      for (pot <- pots) {
        out.append(new TaskObject(pot.name, Some(pot), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = false))
        potNames.append(pot.name)
      }
      out.append( new TaskValueStr("flowerPotNames", potNames.mkString(",")) )

      flowerpots.append( out.toArray )
    }

  }

  // Variation 3: Answer boxes
  val answerBoxes = new ArrayBuffer[ Array[TaskModifier] ]()
  val answerBoxColors = Array("red", "green", "blue", "orange")
  for (location <- locations) {
    for (i <- 0 until answerBoxColors.length-1) {
      val colorDom = answerBoxColors(i)
      val colorRec = answerBoxColors(i+1)
      val boxDom = new AnswerBox(colorDom)
      val boxRec = new AnswerBox(colorRec)
      answerBoxes.append(Array(
        new TaskObject(boxDom.name, Some(boxDom), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
        new TaskObject(boxRec.name, Some(boxRec), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
        new TaskValueStr(key = "answerBoxDom", boxDom.name),
        new TaskValueStr(key = "answerBoxRec", boxRec.name)
      ))
    }
  }


  // Combinations
  var combinations = for {
    i <- genetics
    j <- flowerpots
    k <- answerBoxes
  } yield List(i, j, k)

  println("Genetics: " + genetics.length)
  println("Flowerpots: " + flowerpots.length)
  println("AB: " + answerBoxes.length)

  println("Number of combinations: " + combinations.length)

  def numCombinations():Int = this.combinations.size

  def getCombination(idx:Int):Array[TaskModifier] = {
    val out = new ArrayBuffer[TaskModifier]
    for (elem <- combinations(idx)) {
      out.insertAll(out.length, elem)
    }
    // Return
    out.toArray
  }

  // Setup a particular modifier combination on the universe
  private def setupCombination(modifiers:Array[TaskModifier], universe:EnvObject, agent:Agent):(Boolean, String) = {
    // Run each modifier's change on the universe
    for (mod <- modifiers) {
      println("Running modifier: " + mod.toString)
      val success = mod.runModifier(universe, agent)
      if (!success) {
        return (false, "ERROR: Error running one or more modifiers while setting up task environment.")
      }
    }
    // If we reach here, success
    return (true, "")
  }

  def setupCombination(combinationNum:Int, universe:EnvObject, agent:Agent): (Boolean, String) = {
    if (combinationNum >= this.numCombinations()) {
      return (false, "ERROR: The requested variation (" + combinationNum + ") exceeds the total number of variations (" + this.numCombinations() + ").")
    }
    return this.setupCombination( this.getCombination(combinationNum), universe, agent )
  }


  // Setup a set of subgoals for this task modifier combination.
  private def setupGoals(modifiers:Array[TaskModifier], combinationNum:Int): Task = {
    // Step 1: Find seed type
    val traitName = this.getTaskValueStr(modifiers, "traitName")
    if (traitName.isEmpty) throw new RuntimeException("ERROR: Failed to find trait name.")
    val traitValue = this.getTaskValueStr(modifiers, "traitValue")
    if (traitValue.isEmpty) throw new RuntimeException("ERROR: Failed to find trait value.")
    val domOrRec = this.getTaskValueStr(modifiers, "domOrRec")
    if (domOrRec.isEmpty) throw new RuntimeException("ERROR: Failed to find whether trait is dominant or recessive.")
    val plantName = this.getTaskValueStr(modifiers, "plantName")
    if (plantName.isEmpty) throw new RuntimeException("ERROR: Failed to find plant name.")
    val answerBoxDom = this.getTaskValueStr(modifiers, "answerBoxDom")
    if (answerBoxDom.isEmpty) throw new RuntimeException("ERROR: Failed to find answer box (dominant).")
    val answerBoxRec = this.getTaskValueStr(modifiers, "answerBoxRec")
    if (answerBoxRec.isEmpty) throw new RuntimeException("ERROR: Failed to find answer box (recessive).")

    val flowerPotNames = this.getTaskValueStr(modifiers, "flowerPotNames").get.split(",")
    val seedType = this.getTaskValueStr(modifiers, "seedType").get

    val gSequence = new ArrayBuffer[Goal]
    val gSequenceUnordered = new ArrayBuffer[Goal]
    var description:String = "<empty>"
    if (mode == MODE_MENDEL_UNKNOWN) {

      if (domOrRec.get == GeneticTrait.DOMINANT) {
        // Dominant
        gSequence.append(new GoalFind(objectName = answerBoxDom.get, failIfWrong = true, _defocusOnSuccess = true, description = "focus on the correct answer box"))
      } else {
        // Recessive
        gSequence.append(new GoalFind(objectName = answerBoxRec.get, failIfWrong = true, _defocusOnSuccess = true, description = "focus on the correct answer box"))
      }

      // Seed Jar
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = "seed jar", _isOptional = true, description = "be in same location as seed jar"))
      gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName = "inventory", validObjectNames = Array("seed jar"), _isOptional = true, key = "haveSeedJar", description = "have seed jar in inventory"))

      // Moving to helpful locations
      gSequenceUnordered.append(new GoalMoveToNewLocation(_isOptional = true, unlessInLocation = "", description = "move to a new location") )            // Move to any new location
      gSequenceUnordered.append(new GoalMoveToLocation("greenhouse", _isOptional = true, key = "move1", description = "move to the greenhouse") )
      gSequenceUnordered.append(new GoalMoveToLocation("greenhouse", _isOptional = true, key = "move2", keysMustBeCompletedBefore = Array("haveSeedJar"), description = "move to the greenhouse (after having seed jar)") )

      // Have soil in flower pots
      var cIdx:Int = 1
      for (containerName <- flowerPotNames) {
        gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName, validObjectNames = Array("soil"), _isOptional = true, description = "have soil in flower pot (" + cIdx + ")"))
        cIdx += 1
      }

      // Have water in flower pots
      var wIdx:Int = 1
      for (containerName <- flowerPotNames) {
        gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName, validObjectNames = Array("water"), _isOptional = true, description = "have water in flower pot (" + wIdx + ")"))
        wIdx += 1
      }

      // Have seeds in flower pots
      var sIdx:Int = 1
      for (containerName <- flowerPotNames) {
        gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName, validObjectNames = Array(seedType + " seed"), _isOptional = true, description = "have seed in flower pot (" + sIdx + ")"))
        sIdx += 1
      }

      // Have plants grow through life stages
      for (numToFind <- 1 to 6) {
        gSequenceUnordered.append(new GoalLifeStageAnywhere(lifeFormType = seedType, lifeStageName = PLANT_STAGE_SEED, minNumToFind = numToFind, description = "have at least " + numToFind + " plants as seeds"))
        gSequenceUnordered.append(new GoalLifeStageAnywhere(lifeFormType = seedType, lifeStageName = PLANT_STAGE_SEEDLING, minNumToFind = numToFind, description = "have at least " + numToFind + " plants as seedlings"))
        gSequenceUnordered.append(new GoalLifeStageAnywhere(lifeFormType = seedType, lifeStageName = PLANT_STAGE_ADULT_PLANT, minNumToFind = numToFind, description = "have at least " + numToFind + " plants as adult plants"))
        gSequenceUnordered.append(new GoalLifeStageAnywhere(lifeFormType = seedType, lifeStageName = PLANT_STAGE_REPRODUCING, minNumToFind = numToFind, key = "atLeast" + numToFind + "Reproducing", description = "have at least " + numToFind + " plants as reproducing plants"))
      }

      // Have pollinators in the same room as plants
      gSequenceUnordered.append(new GoalContainerOpen(containerName = "bee hive", _isOptional = true, keysMustBeCompletedBefore = Array("atLeast2Reproducing"), description = "bee hive open (after reprod. life stage)"))
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = "adult bee", _isOptional = true, keysMustBeCompletedBefore = Array("atLeast2Reproducing"), description = "be in same location as pollinator (after reprod. life stage)"))

      // Have a seed grow on the plant (i.e., be in the same location as that seed, on the tree)
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = seedType, _isOptional = true, keysMustBeCompletedBefore = Array("atLeast2Reproducing"), description = "be in same location as grown seed"))


      description = "Your task is to determine whether " + traitValue.get + " " + traitName.get + " is a dominant or recessive trait in the " + plantName.get + ". "
      description += "If the trait is dominant, focus on the " + answerBoxDom.get + ". "
      description += "If the trait is recessive, focus on the " + answerBoxRec.get + ". "

    } else {
      throw new RuntimeException("ERROR: Unrecognized task mode: " + mode)
    }

    val taskLabel = taskName + "-variation" + combinationNum
    //val description = "Your task is to find a " + subTask + ". First, focus on the thing. Then, move it to the " + answerBoxName + " in the " + answerBoxLocation + "."
    val goalSequence = new GoalSequence(gSequence.toArray, gSequenceUnordered.toArray)

    val task = new Task(taskName, description, goalSequence, taskModifiers = modifiers)

    // Return
    return task
  }

  def setupGoals(combinationNum:Int): Task = {
    this.setupGoals( this.getCombination(combinationNum), combinationNum )
  }


  /*
   * Gold Action Sequences
   */
  def mkGoldActionSequence(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String]) = {
    if (mode == MODE_MENDEL_UNKNOWN) {
      return mkGoldActionSequenceMendel(modifiers, runner)
    } else {
      throw new RuntimeException("ERROR: Unrecognized task mode: " + mode)
    }

  }

  /*
   * Gold action sequences
   */
  def mkGoldActionSequenceMendel(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String]) = {
    val universe = runner.agentInterface.get.universe
    val agent = runner.agentInterface.get.agent

    // Task variables
    val traitName = this.getTaskValueStr(modifiers, "traitName").get
    val traitValue = this.getTaskValueStr(modifiers, "traitValue").get
    val domOrRec = this.getTaskValueStr(modifiers, "domOrRec").get
    val answerBoxDom = this.getTaskValueStr(modifiers, "answerBoxDom").get
    val answerBoxRec = this.getTaskValueStr(modifiers, "answerBoxRec").get

    val flowerPotNames = this.getTaskValueStr(modifiers, "flowerPotNames").get.split(",")
    val seedType = this.getTaskValueStr(modifiers, "seedType").get

    val seedLocation = "greenhouse"

    // Step 1: Move from starting location to task location
    val startLocation = agent.getContainer().get.name
    val (actions, actionStrs) = PathFinder.createActionSequence(universe, agent, startLocation, endLocation = seedLocation)
    runActionSequence(actionStrs, runner)

    // Look around
    runAction("look around", runner)

    // Take seed jar
    val seedJars = PathFinder.getAllAccessibleEnvObject(queryName = "seed jar", getCurrentAgentLocation(runner))
    if (seedJars.length == 0) return (false, getActionHistory(runner))
    val seedJar = seedJars(0)
    //runAction("pick up " + PathFinder.getObjUniqueReferent(seedJar, getCurrentAgentLocation(runner)).get, runner)
    runAction("pick up seed jar", runner)

    /*
    // Go to greenhouse
    val (actions1, actionStrs1) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = "greenhouse")
    runActionSequence(actionStrs1, runner)
     */

    // Look around
    runAction("look around", runner)

    // Get references to flower pots (and sort them by those with and without soil)
    val flowerpots = Random.shuffle((getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[FlowerPot]() ++ getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[SelfWateringFlowerPot]()).toList.sortBy(_.uuid))
    val flowerPotsWithSoil = new ArrayBuffer[EnvObject]
    val flowerPotsWithoutSoil = new ArrayBuffer[EnvObject]

    for (pot <- flowerpots) {
      val soil = pot.getContainedAccessibleObjectsOfType[Soil]()
      if (soil.size > 0) {
        flowerPotsWithSoil.append(pot)
      } else {
        flowerPotsWithoutSoil.append(pot)
      }
    }

    var attempts:Int = 0
    val NUM_POTS_TO_PREPARE:Int = 6
    while (flowerPotsWithSoil.size < NUM_POTS_TO_PREPARE) {
      // See what the soil situation is like
      val soilInRoom = getCurrentAgentLocation(runner).getContainedObjectsOfType[Soil]().toArray

      //## runAction("NOTE: " + flowerPotsWithSoil.size + " pots have soil.", runner)

      // Case 1: Flower pot already exists with soil inside
      if (flowerPotsWithSoil.size >= NUM_POTS_TO_PREPARE) {
        // No need to do more
      } else {
        // Add soil to a flower pot

        // Case 2: Soil is accessible in room, just move it into the pot
        if (soilInRoom.size > 0) {
          val pot = flowerPotsWithoutSoil(0)
          // Move soil to flower pot
          TaskParametric.runAction("move " + PathFinder.getObjUniqueReferent(soilInRoom(0), getCurrentAgentLocation(runner)).get + " to " + PathFinder.getObjUniqueReferent(pot, TaskParametric.getCurrentAgentLocation(runner)).get, runner)
          // Move pot reference to list of pots with soil
          flowerPotsWithoutSoil.remove(0)
          flowerPotsWithSoil.append(pot)
        } else {
          // Case 3: Soil is not in room, have to go dig it up
          val pot = flowerPotsWithoutSoil(0)

          // Take shovel (if it's in this location)
          var agentHasShovel: Boolean = false
          if (getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[Shovel]().size > 0) {
            TaskParametric.runAction("pick up shovel", runner)
            agentHasShovel = true
          }

          // Go outside
          val (actions2, actionStrs2) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = "outside")
          runActionSequence(actionStrs2, runner)

          // Take shovel (if it's in this location)
          if ((!agentHasShovel) && (getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[Shovel]().size > 0)) {
            TaskParametric.runAction("pick up shovel", runner)
          }

          // Use shovel on ground
          TaskParametric.runAction("use shovel in inventory on ground", runner)

          // Pick up dirt
          TaskParametric.runAction("pick up soil", runner)

          // Go back to the greenhouse
          val (actions3, actionStrs3) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = "greenhouse")
          runActionSequence(actionStrs3, runner)

          // Move soil to flower pot
          TaskParametric.runAction("move soil in inventory to " + PathFinder.getObjUniqueReferent(pot, TaskParametric.getCurrentAgentLocation(runner)).get, runner)

          // Move pot reference to list of pots with soil
          flowerPotsWithoutSoil.remove(0)
          flowerPotsWithSoil.append(pot)
        }

      }

      // Check for infinite loops in case conditions can't be satisfied
      attempts += 1
      if (attempts > 4) {
        runAction("ERROR: Ending early -- max attempts exceeded (" + attempts + ")", runner)
        return (false, getActionHistory(runner))
      }
    }


    // Put seeds in flower pots
    val NUM_PLANTS_TO_GROW:Int = 2
    val flowerPotsWithSeeds = new ArrayBuffer[EnvObject]()
    for (i <- 0 until NUM_PLANTS_TO_GROW) {
      val flowerpot = flowerPotsWithSoil(0)

      // Move seed to flower pot
      val seedName = seedType + " seed in seed jar"
      TaskParametric.runAction("move " + seedName + " to " + PathFinder.getObjUniqueReferent(flowerpot, TaskParametric.getCurrentAgentLocation(runner)).get, runner)
      //TaskParametric.runAction("0", runner) // Ambiguity resolution

      flowerPotsWithSeeds.append(flowerpot)
      flowerPotsWithSoil.remove(0)
    }


    // TODO: Do watering
    // Pick up water jug
    val waterJug = getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[Jug]().toList.head
    val sink = getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[Sink]().toList.head


    // Watering cycle
    var beesReleased:Boolean = false
    var done:Boolean = false
    var cycles:Int = 0
    while (!done && cycles < 10) {      // Wait 15 cycles, which should be enough time for the bees to do their thing
      // Water plants regularly

      // Turn on sink
      runAction("activate " + PathFinder.getObjUniqueReferent(sink, getCurrentAgentLocation(runner)).get, runner)

      // Water plant
      for (flowerPotToWater <- flowerPotsWithSeeds) {
        runAction("move " + PathFinder.getObjUniqueReferent(waterJug, getCurrentAgentLocation(runner)).get + " to " + PathFinder.getObjUniqueReferent(sink, getCurrentAgentLocation(runner)).get, runner)
        runAction("pour " + PathFinder.getObjUniqueReferent(waterJug, getCurrentAgentLocation(runner)).get + " into " + PathFinder.getObjUniqueReferent(flowerPotToWater, getCurrentAgentLocation(runner)).get, runner)
      }

      // Turn off sink
      runAction("deactivate " + PathFinder.getObjUniqueReferent(sink, getCurrentAgentLocation(runner)).get, runner)

      // Check if at least plants are at reproducing stage
      if (!beesReleased) {
        var foundReproducing:Boolean = false

        breakable {
          for (flowerpot <- flowerPotsWithSeeds) {
            val plants = flowerpot.getContainedAccessibleObjectsOfType[Plant]().toList
            for (plant <- plants) {
              plant match {
                case p:LivingThing => {
                  if (p.lifecycle.get.getCurStageName() == PLANT_STAGE_REPRODUCING) {
                    foundReproducing = true
                    break()
                  }
                }
              }
            }
          }
        }

        if (foundReproducing) {
          // Release the pollinators

          // First, close all the doors
          for (portal <- getCurrentAgentLocation(runner).getPortals(includeHidden = false)) {
            runAction("close " + PathFinder.getObjUniqueReferent(portal, getCurrentAgentLocation(runner)).get, runner)
          }

          // Then, open the bee hive
          val beehive = getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[BeeHive]().toList(0)
          runAction("open " + PathFinder.getObjUniqueReferent(beehive, getCurrentAgentLocation(runner)).get, runner)

          beesReleased = true
        }
      }

      // Check for new seeds that have been produced by the plants
      val peaplants = Random.shuffle(getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[RandomGeneticsPlants]().toList.sortBy(_.uuid))
      val newSeeds = new ArrayBuffer[EnvObject]
      for (plant <- peaplants) {
        plant match {
          case pl:LivingThing => {
            if (pl.lifecycle.get.getCurStageName() == PLANT_STAGE_SEED) {
              newSeeds.append(plant)
            }
          }
        }
      }

      // Check if there are enough seeds to harvest them
      if (newSeeds.size >= 6) {
        for (seed <- newSeeds) {
          runAction("move " + PathFinder.getObjUniqueReferent(seed, getCurrentAgentLocation(runner)).get + " to " + PathFinder.getObjUniqueReferent(seedJar, getCurrentAgentLocation(runner)).get, runner)
          //runAction("0", runner)    // In case it's ambiguous
        }
        done = true
      }

      if (!done) {
        for (j <- 0 until 5) {
          runAction("wait1", runner)
        }
      }

      runAction("look around", runner)

      // Keep track of number of cycles, so we don't get stuck in an infinite loop if conditions aren't met.
      cycles += 1
    }

    runAction("look at seed jar", runner)


    /*
     * Plant second generation
     */
    flowerPotsWithSeeds.clear()
    for (i <- 0 until 4) {
      val flowerpot = flowerPotsWithSoil(0)

      // Move seed to flower pot
      val seedName = seedType + " seed in seed jar"
      TaskParametric.runAction("move " + seedName + " to " + PathFinder.getObjUniqueReferent(flowerpot, TaskParametric.getCurrentAgentLocation(runner)).get, runner)
      //TaskParametric.runAction("0", runner) // Ambiguity resolution

      flowerPotsWithSeeds.append(flowerpot)
      flowerPotsWithSoil.remove(0)
    }

    // Watering cycle for second-generation plants
    done = false
    cycles = 0
    val adultPlants = new ArrayBuffer[EnvObject]()
    while (!done && cycles < 10) {      // Wait 15 cycles, which should be enough time for the bees to do their thing
      // Water plants regularly

      // Turn on sink
      runAction("activate " + PathFinder.getObjUniqueReferent(sink, getCurrentAgentLocation(runner)).get, runner)

      // Water plant
      for (flowerPotToWater <- flowerPotsWithSeeds) {
        runAction("move " + PathFinder.getObjUniqueReferent(waterJug, getCurrentAgentLocation(runner)).get + " to " + PathFinder.getObjUniqueReferent(sink, getCurrentAgentLocation(runner)).get, runner)
        runAction("pour " + PathFinder.getObjUniqueReferent(waterJug, getCurrentAgentLocation(runner)).get + " into " + PathFinder.getObjUniqueReferent(flowerPotToWater, getCurrentAgentLocation(runner)).get, runner)
      }

      // Turn off sink
      runAction("deactivate " + PathFinder.getObjUniqueReferent(sink, getCurrentAgentLocation(runner)).get, runner)

      // Check for a minimum number of adult plants
      val peaplants = Random.shuffle(getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[RandomGeneticsPlants]().toList.sortBy(_.uuid))
      for (plant <- peaplants) {
        plant match {
          case pl:LivingThing => {
            if ((pl.lifecycle.get.getCurStageName() == PLANT_STAGE_ADULT_PLANT) || (pl.lifecycle.get.getCurStageName() == PLANT_STAGE_REPRODUCING)) {
              adultPlants.append(plant)
            }
          }
        }
      }

      // If we have at least 4 new adult plants, we're done
      if (adultPlants.size >= 4) {
        done = true
      } else {
        // Clear the count for next time, so we don't accidentally double count them
        adultPlants.clear()
      }

      if (!done) {
        for (j <- 0 until 5) {
          runAction("wait1", runner)
        }
      }

      runAction("look around", runner)

      // Keep track of number of cycles, so we don't get stuck in an infinite loop if conditions aren't met.
      cycles += 1
    }


    // Count features on adult plants
    var numObservationsOfTrait:Int = 0
    for (adultPlant <- adultPlants) {
      if (adultPlant.propChromosomePairs.isDefined) {
        if (adultPlant.propChromosomePairs.get.getPhenotypeValue(traitName).getOrElse("") == traitValue) {
          numObservationsOfTrait += 1
        }
        //runAction("OBSERVATION " + traitName + " " + adultPlant.propChromosomePairs.get.getPhenotypeValue(traitName), runner)
      }
    }

    ////## runAction("NOTE: Number of observations of trait: " + numObservationsOfTrait, runner)

    if (numObservationsOfTrait > (adultPlants.size/2)) {
      // Observed frequently -- likely a dominant trait
      runAction("focus on " + answerBoxDom, runner)
    } else {
      // Observed infrequently -- likely a recessive trait
      runAction("focus on " + answerBoxRec, runner)
    }


    // Wait one moment
    runAction("wait1", runner)

    // Return
    return (true, getActionHistory(runner))
  }


}


object TaskMendelianGenetics2 {
  val MODE_MENDEL_UNKNOWN             = "mendelian genetics (unknown plant)"

  def registerTasks(taskMaker:TaskMaker1): Unit = {
    taskMaker.addTask( new TaskMendelianGenetics2(mode = MODE_MENDEL_UNKNOWN) )
  }


  /*
   * Helper functions
   */


  // Make a set of inclined planes
  def mkUnknownPlantSeedJar(plantIdx: Int, traitName: String): EnvObject = {
    // Seed jar
    val jar = new CeramicCup() // TODO, make jar
    jar.name = "seed jar"

    if (plantIdx == 0) {
      // Double-dominant
      val dom = GeneticTraitUnknownPlantE.mkRandomChromosomePairExcept(traitName, GeneticTrait.DOMINANT, GeneticTrait.DOMINANT)
      val plantDom = new RandomGeneticsPlantsE(_chromosomePairs = Some(dom))
      jar.addObject(plantDom)
      // Double-recessive
      val rec = GeneticTraitUnknownPlantE.mkRandomChromosomePairExcept(traitName, GeneticTrait.RECESSIVE, GeneticTrait.RECESSIVE)
      val plantRec = new RandomGeneticsPlantsE(_chromosomePairs = Some(rec))
      jar.addObject(plantRec)

    } else if (plantIdx == 1) {
      // Double-dominant
      val dom = GeneticTraitUnknownPlantB.mkRandomChromosomePairExcept(traitName, GeneticTrait.DOMINANT, GeneticTrait.DOMINANT)
      val plantDom = new RandomGeneticsPlantsB(_chromosomePairs = Some(dom))
      jar.addObject(plantDom)
      // Double-recessive
      val rec = GeneticTraitUnknownPlantB.mkRandomChromosomePairExcept(traitName, GeneticTrait.RECESSIVE, GeneticTrait.RECESSIVE)
      val plantRec = new RandomGeneticsPlantsB(_chromosomePairs = Some(rec))
      jar.addObject(plantRec)

    } else if (plantIdx == 2) {
      // Double-dominant
      val dom = GeneticTraitUnknownPlantC.mkRandomChromosomePairExcept(traitName, GeneticTrait.DOMINANT, GeneticTrait.DOMINANT)
      val plantDom = new RandomGeneticsPlantsC(_chromosomePairs = Some(dom))
      jar.addObject(plantDom)
      // Double-recessive
      val rec = GeneticTraitUnknownPlantC.mkRandomChromosomePairExcept(traitName, GeneticTrait.RECESSIVE, GeneticTrait.RECESSIVE)
      val plantRec = new RandomGeneticsPlantsC(_chromosomePairs = Some(rec))
      jar.addObject(plantRec)

    } else if (plantIdx == 3) {
      // Double-dominant
      val dom = GeneticTraitUnknownPlantD.mkRandomChromosomePairExcept(traitName, GeneticTrait.DOMINANT, GeneticTrait.DOMINANT)
      val plantDom = new RandomGeneticsPlantsD(_chromosomePairs = Some(dom))
      jar.addObject(plantDom)
      // Double-recessive
      val rec = GeneticTraitUnknownPlantD.mkRandomChromosomePairExcept(traitName, GeneticTrait.RECESSIVE, GeneticTrait.RECESSIVE)
      val plantRec = new RandomGeneticsPlantsD(_chromosomePairs = Some(rec))
      jar.addObject(plantRec)

    } else {
      throw new RuntimeException("ERROR: Unknown plant index (" + plantIdx + ").")
    }


    // Return
    jar
  }



  // Make N flower pots
  def mkFlowerPots(numPots:Int): Array[EnvObject] = {
    val maxIdx = 10

    // Make N uniquely-named flower pots
    val pots = new ArrayBuffer[EnvObject]()
    for (i <- 1 until maxIdx) {
      val flowerpot = new FlowerPot()
      flowerpot.name = "flower pot " + i
      flowerpot.addObject( new Soil() )
      pots.append(flowerpot)
    }

    // Shuffle them, and take N
    val shuffled = Random.shuffle(pots).toArray

    // Return
    return shuffled.slice(0, numPots)
  }


  def main(args:Array[String]): Unit = {
    val traitName = "seed color"

    // Double-dominant
    val dom = GeneticTraitUnknownPlantE.mkRandomChromosomePairExcept(traitName, GeneticTrait.DOMINANT, GeneticTrait.DOMINANT)
    val plantDom = new RandomGeneticsPlantsE(_chromosomePairs = Some(dom))

    // Double-recessive
    val rec = GeneticTraitUnknownPlantE.mkRandomChromosomePairExcept(traitName, GeneticTrait.RECESSIVE, GeneticTrait.RECESSIVE)
    val plantRec = new RandomGeneticsPlantsE(_chromosomePairs = Some(rec))


    val parent1Chromosomes = plantDom.propChromosomePairs
    //val parent2Chromosomes = parentPlant.propChromosomePairs
    val parent2Chromosomes = plantRec.propChromosomePairs

    val fruit = PlantReproduction.createFruit(plantDom.getPlantType(), parent1Chromosomes, parent2Chromosomes)


  }

}
