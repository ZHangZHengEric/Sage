package scienceworld.tasks.specifictasks

//TODO: Only part-way implemented

import scienceworld.actions.Action
import scienceworld.environments.ContainerMaker
import scienceworld.goldagent.PathFinder
import scienceworld.objects.agent.Agent
import scienceworld.objects.containers.furniture.BeeHive
import scienceworld.objects.containers.{CeramicCup, FlowerPot, Jug, SelfWateringFlowerPot}
import scienceworld.objects.devices.{Shovel, Sink, Stove}
import scienceworld.objects.livingthing.LivingThing
import scienceworld.objects.livingthing.plant.{AppleTree, Plant, Soil}
import scienceworld.objects.misc.InclinedPlane
import scienceworld.objects.substance.food.Fruit
import scienceworld.objects.taskitems.AnswerBox
import scienceworld.processes.PlantReproduction
import scienceworld.processes.lifestage.PlantLifeStages.{PLANT_STAGE_ADULT_PLANT, PLANT_STAGE_REPRODUCING, PLANT_STAGE_SEED, PLANT_STAGE_SEEDLING}
import scienceworld.properties.LeadProp
import scienceworld.runtime.pythonapi.PythonInterface
import scienceworld.struct.EnvObject
import scienceworld.tasks.{Task, TaskDisable, TaskMaker1, TaskModifier, TaskObject, TaskValueStr}
import scienceworld.tasks.goals.{Goal, GoalSequence}
import scienceworld.tasks.goals.specificgoals.{GoalActivateDeviceWithName, GoalChangeStateOfMatter, GoalContainerOpen, GoalFind, GoalFocusOnAnimal, GoalFocusOnLivingThing, GoalFocusOnNonlivingThing, GoalFocusOnPlant, GoalInRoomWithObject, GoalIsDifferentStateOfMatter, GoalIsNotStateOfMatter, GoalIsStateOfMatter, GoalLifeStage, GoalLifeStageAnywhere, GoalMoveToLocation, GoalMoveToNewLocation, GoalObjectInContainer, GoalObjectsInSingleContainer, GoalPastActionUseObjectOnObject, GoalSpecificObjectInDirectContainer, GoalTemperatureIncrease, GoalTemperatureOnFire}
import scienceworld.tasks.specifictasks.TaskChangeOfState.{MODE_BOIL, MODE_CHANGESTATE, MODE_FREEZE, MODE_MELT}
import scienceworld.tasks.specifictasks.TaskFindLivingNonLiving.{MODE_ANIMAL, MODE_LIVING, MODE_NONLIVING, MODE_PLANT}
import scienceworld.tasks.specifictasks.TaskGrowPlant.{MODE_GROW_FRUIT, MODE_GROW_PLANT}
import scienceworld.tasks.specifictasks.TaskInclinedPlane1.actionSequenceMeasureBlockFallTime

import scala.collection.mutable.ArrayBuffer
import scala.util.Random
import scala.util.control.Breaks.{break, breakable}


class TaskGrowPlant(val mode:String = MODE_LIVING) extends TaskParametric {
  val taskName = mode.replaceAll(" ", "-").replaceAll("[()]", "")


  // Variation 1: Which seeds to grow
  val seeds = new ArrayBuffer[ Array[TaskModifier] ]()
  val locations = Array("kitchen", "bathroom", "living room", "bedroom", "workshop", "greenhouse")
  //val locations = Array("greenhouse")
  for (location <- locations) {

    val seedJarApple = TaskGrowPlant.mkSeedJar(PlantReproduction.PLANT_APPLE)
    seeds.append(Array(new TaskObject(seedJarApple.name, Some(seedJarApple), roomToGenerateIn = location, Array.empty[String], generateNear = 0), new TaskValueStr("seedType", PlantReproduction.PLANT_APPLE), new TaskValueStr("location", location)))

    val seedJarAvocado = TaskGrowPlant.mkSeedJar(PlantReproduction.PLANT_AVOCADO)
    seeds.append(Array(new TaskObject(seedJarAvocado.name, Some(seedJarAvocado), roomToGenerateIn = location, Array.empty[String], generateNear = 0), new TaskValueStr("seedType", PlantReproduction.PLANT_AVOCADO), new TaskValueStr("location", location)))

    val seedJarBanana = TaskGrowPlant.mkSeedJar(PlantReproduction.PLANT_BANANA)
    seeds.append(Array(new TaskObject(seedJarBanana.name, Some(seedJarBanana), roomToGenerateIn = location, Array.empty[String], generateNear = 0), new TaskValueStr("seedType", PlantReproduction.PLANT_BANANA), new TaskValueStr("location", location)))

    val seedJarCherry = TaskGrowPlant.mkSeedJar(PlantReproduction.PLANT_CHERRY)
    seeds.append(Array(new TaskObject(seedJarCherry.name, Some(seedJarCherry), roomToGenerateIn = location, Array.empty[String], generateNear = 0), new TaskValueStr("seedType", PlantReproduction.PLANT_CHERRY), new TaskValueStr("location", location)))

    val seedJarLemon = TaskGrowPlant.mkSeedJar(PlantReproduction.PLANT_LEMON)
    seeds.append(Array(new TaskObject(seedJarLemon.name, Some(seedJarLemon), roomToGenerateIn = location, Array.empty[String], generateNear = 0), new TaskValueStr("seedType", PlantReproduction.PLANT_LEMON), new TaskValueStr("location", location)))

    val seedJarOrange = TaskGrowPlant.mkSeedJar(PlantReproduction.PLANT_ORANGE)
    seeds.append(Array(new TaskObject(seedJarOrange.name, Some(seedJarOrange), roomToGenerateIn = location, Array.empty[String], generateNear = 0), new TaskValueStr("seedType", PlantReproduction.PLANT_ORANGE), new TaskValueStr("location", location)))

    val seedJarPeach = TaskGrowPlant.mkSeedJar(PlantReproduction.PLANT_PEACH)
    seeds.append(Array(new TaskObject(seedJarApple.name, Some(seedJarPeach), roomToGenerateIn = location, Array.empty[String], generateNear = 0), new TaskValueStr("seedType", PlantReproduction.PLANT_PEACH), new TaskValueStr("location", location)))

  }

  // Sort seeds by seed name (so that unseen seeds will show up in the dev set)
  val seedsSorted = seeds.sortBy(getTaskValueStr(_, "seedType"))


  // Variation 2: What containers are available to grow the seeds in
  val plantContainers = new ArrayBuffer[ Array[TaskModifier] ]()
  val numContainers = 3

  // Case 1: N flower pots, with soil inside
  val case1tm = new ArrayBuffer[TaskModifier]()
  val containerNames1 = new ArrayBuffer[String]
  for (i <- 0 until numContainers) {
    val container = new FlowerPot()
    container.name = "flower pot " + (i+1)
    container.addObject( new Soil() )
    case1tm.append( new TaskObject(container.name, Some(container), roomToGenerateIn = "greenhouse", Array.empty[String], generateNear = 0))
    containerNames1.append(container.name)
  }
  case1tm.append( new TaskValueStr("containerNames", containerNames1.mkString(",")))
  plantContainers.append( case1tm.toArray )


  // Case 2: N flower pots, no soil inside (but, soil nearby)
  val case2tm = new ArrayBuffer[TaskModifier]()
  val containerNames2 = new ArrayBuffer[String]
  for (i <- 0 until numContainers) {
    val container = new FlowerPot()
    container.name = "flower pot " + (i+1)
    case2tm.append( new TaskObject(container.name, Some(container), roomToGenerateIn = "greenhouse", Array.empty[String], generateNear = 0))
    containerNames2.append(container.name)

    val soil = new Soil()
    case2tm.append( new TaskObject(soil.name, Some(soil), roomToGenerateIn = "greenhouse", Array.empty[String], generateNear = 0))
  }
  case2tm.append( new TaskValueStr("containerNames", containerNames2.mkString(",")))
  plantContainers.append( case2tm.toArray )

  // Case 3: N flower pots, no soil nearby
  val case3tm = new ArrayBuffer[TaskModifier]()
  val containerNames3 = new ArrayBuffer[String]
  for (i <- 0 until numContainers) {
    val container = new FlowerPot()
    container.name = "flower pot " + (i+1)
    case3tm.append( new TaskObject(container.name, Some(container), roomToGenerateIn = "greenhouse", Array.empty[String], generateNear = 0))
    containerNames3.append(container.name)
  }
  case3tm.append( new TaskValueStr("containerNames", containerNames3.mkString(",")))
  plantContainers.append( case3tm.toArray )


  // Case 4: No flower pots.  Only shovel outside?



  // Combinations
  val combinations = for {
    i <- seedsSorted
    j <- plantContainers
  } yield List(i, j)

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

    // The first modifier will be the seed jar.
    val seedType = this.getTaskValueStr(modifiers, "seedType").get
    val seedLocation = this.getTaskValueStr(modifiers, "location").get
    val containerNames = this.getTaskValueStr(modifiers, "containerNames").get.split(",")


    var subTask = ""
    val gSequence = new ArrayBuffer[Goal]
    val gSequenceUnordered = new ArrayBuffer[Goal]

    var description:String = "<empty>"
    if (mode == MODE_GROW_PLANT) {
      gSequence.append( new GoalLifeStage(lifeFormType = seedType, lifeStageName = PLANT_STAGE_SEED, description = "focus plant is in seed stage") )
      gSequence.append( new GoalLifeStage(lifeFormType = seedType, lifeStageName = PLANT_STAGE_SEEDLING, description = "focus plant is in seedling stage") )
      gSequence.append( new GoalLifeStage(lifeFormType = seedType, lifeStageName = PLANT_STAGE_ADULT_PLANT, description = "focus plant is in adult stage") )
      gSequence.append( new GoalLifeStage(lifeFormType = seedType, lifeStageName = PLANT_STAGE_REPRODUCING, description = "focus plant is in reproducing stage") )

      // Seed Jar
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = "seed jar", _isOptional = true, description = "be in same location as seed jar"))
      gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName = "inventory", validObjectNames = Array("seed jar"), _isOptional = true, key = "haveSeedJar", description = "have seed jar in inventory"))

      // Shovel/Soil
      gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName = "inventory", validObjectNames = Array("shovel"), _isOptional = true, description = "have shovel in inventory"))
      gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName = "inventory", validObjectNames = Array("soil"), _isOptional = true, description = "have soil in inventory"))
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = "soil", _isOptional = true, description = "be in same location as soil"))

      // Moving to helpful locations
      gSequenceUnordered.append(new GoalMoveToNewLocation(_isOptional = true, unlessInLocation = "", description = "move to a new location") )            // Move to any new location
      gSequenceUnordered.append(new GoalMoveToLocation("greenhouse", _isOptional = true, key = "move1", description = "move to the greenhouse") )
      gSequenceUnordered.append(new GoalMoveToLocation("greenhouse", _isOptional = true, key = "move2", keysMustBeCompletedBefore = Array("haveSeedJar"), description = "move to the greenhouse (after having seed jar)") )

      // Have soil in flower pots
      var cIdx:Int = 1
      for (containerName <- containerNames) {
        gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName, validObjectNames = Array("soil"), _isOptional = true, description = "have soil in flower pot (" + cIdx + ")"))
        cIdx += 1
      }

      // Have water in flower pots
      var wIdx:Int = 1
      for (containerName <- containerNames) {
        gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName, validObjectNames = Array("water"), _isOptional = true, description = "have water in flower pot (" + wIdx + ")"))
        wIdx += 1
      }

      // Have seeds in flower pots
      var sIdx:Int = 1
      for (containerName <- containerNames) {
        gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName, validObjectNames = Array(seedType + " seed"), _isOptional = true, description = "have seed in flower pot (" + sIdx + ")"))
        sIdx += 1
      }

      description = "Your task is to grow a " + seedType + " plant from seed. Seeds can be found in the " + seedLocation + ". First, focus on a seed. Then, make changes to the environment that grow the plant until it reaches the reproduction life stage."

    } else if (mode == MODE_GROW_FRUIT) {
      // TODO: Currently requires all other apples/fruits to be erased from the environment?  (and possibly all other fruiting trees?)
      gSequence.append( new GoalFind(objectName = seedType, description = "focus on the grown fruit") )     // e.g. "seedtype" will be "apple"

      description = "Your task is to grow a " + seedType + ". This will require growing several plants, and them being crosspollinated to produce fruit.  Seeds can be found in the " + seedLocation + ". To complete the task, focus on the grown " + seedType + "."

      // Seed Jar
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = "seed jar", _isOptional = true, description = "be in same location as seed jar"))
      gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName = "inventory", validObjectNames = Array("seed jar"), _isOptional = true, key = "haveSeedJar", description = "have seed jar in inventory"))

      // Shovel/Soil
      gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName = "inventory", validObjectNames = Array("shovel"), _isOptional = true, description = "have shovel in inventory"))
      gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName = "inventory", validObjectNames = Array("soil"), _isOptional = true, description = "have soil in inventory"))
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = "soil", _isOptional = true, description = "be in same location as soil"))

      // Moving to helpful locations
      gSequenceUnordered.append(new GoalMoveToNewLocation(_isOptional = true, unlessInLocation = "", description = "move to a new location") )            // Move to any new location
      gSequenceUnordered.append(new GoalMoveToLocation("greenhouse", _isOptional = true, key = "move1", description = "move to the greenhouse") )
      gSequenceUnordered.append(new GoalMoveToLocation("greenhouse", _isOptional = true, key = "move2", keysMustBeCompletedBefore = Array("haveSeedJar"), description = "move to the greenhouse (after having seed jar)") )

      // Have soil in flower pots
      var cIdx:Int = 1
      for (containerName <- containerNames) {
        gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName, validObjectNames = Array("soil"), _isOptional = true, description = "have soil in flower pot (" + cIdx + ")"))
        cIdx += 1
      }

      // Have water in flower pots
      var wIdx:Int = 1
      for (containerName <- containerNames) {
        gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName, validObjectNames = Array("water"), _isOptional = true, description = "have water in flower pot (" + wIdx + ")"))
        wIdx += 1
      }

      // Have seeds in flower pots
      var sIdx:Int = 1
      for (containerName <- containerNames) {
        gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName, validObjectNames = Array(seedType + " seed"), _isOptional = true, description = "have seed in flower pot (" + sIdx + ")"))
        sIdx += 1
      }

      // Have plants grow through life stages
      for (numToFind <- 1 to 2) {
        gSequenceUnordered.append(new GoalLifeStageAnywhere(lifeFormType = seedType, lifeStageName = PLANT_STAGE_SEED, minNumToFind = numToFind, description = "have at least " + numToFind + " plants as seeds"))
        gSequenceUnordered.append(new GoalLifeStageAnywhere(lifeFormType = seedType, lifeStageName = PLANT_STAGE_SEEDLING, minNumToFind = numToFind, description = "have at least " + numToFind + " plants as seedlings"))
        gSequenceUnordered.append(new GoalLifeStageAnywhere(lifeFormType = seedType, lifeStageName = PLANT_STAGE_ADULT_PLANT, minNumToFind = numToFind, description = "have at least " + numToFind + " plants as adult plants"))
        gSequenceUnordered.append(new GoalLifeStageAnywhere(lifeFormType = seedType, lifeStageName = PLANT_STAGE_REPRODUCING, minNumToFind = numToFind, key = "atLeast" + numToFind + "Reproducing", description = "have at least " + numToFind + " plants as reproducing plants"))
      }

      // Have pollinators in the same room as plants
      gSequenceUnordered.append(new GoalContainerOpen(containerName = "bee hive", _isOptional = true, description = "bee hive open (after reprod. life stage)"))
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = "adult bee", _isOptional = true, keysMustBeCompletedBefore = Array("atLeast2Reproducing"), description = "be in same location as pollinator (after reprod. life stage)"))

      // Have a fruit grow on the plant (i.e., be in the same location as that fruit, on the tree)
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = seedType, _isOptional = true, description = "be in same location as fruit"))


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
    if (mode == MODE_GROW_PLANT) {
      return mkGoldActionSequenceGrowPlant(modifiers, runner)
    } else if (mode == MODE_GROW_FRUIT) {
      return mkGoldActionSequenceGrowFruits(modifiers, runner)
    } else {
      throw new RuntimeException("ERROR: Unrecognized task mode: " + mode)
    }

  }

  /*
   * Gold action sequences
   */
  def mkGoldActionSequenceGrowFruits(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String]) = {
    val universe = runner.agentInterface.get.universe
    val agent = runner.agentInterface.get.agent

    // Task variables
    val seedType = this.getTaskValueStr(modifiers, "seedType").get
    val seedLocation = this.getTaskValueStr(modifiers, "location").get
    val containerNames = this.getTaskValueStr(modifiers, "containerNames").get.split(",")


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

    // Go to greenhouse
    val (actions1, actionStrs1) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = "greenhouse")
    runActionSequence(actionStrs1, runner)

    // Look around
    runAction("look around", runner)

    // Get references to flower pots (and sort them by those with and without soil)
    val fps = getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[FlowerPot]() ++ getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[SelfWateringFlowerPot]()  // Determinism
    val flowerpots = Random.shuffle(fps.toList.sortBy(_.uuid))
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
    val NUM_PLANTS_TO_GROW:Int = 3
    while (flowerPotsWithSoil.size < NUM_PLANTS_TO_GROW) {
      // See what the soil situation is like
      val soilInRoom = getCurrentAgentLocation(runner).getContainedObjectsOfType[Soil]().toArray

      ////## runAction("NOTE: " + flowerPotsWithSoil.size + " pots have soil.", runner)

      // Case 1: Flower pot already exists with soil inside
      if (flowerPotsWithSoil.size >= NUM_PLANTS_TO_GROW) {
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
        //runAction("ERROR: Ending early -- max attempts exceeded (" + attempts + ")", runner)
        return (false, getActionHistory(runner))
      }
    }


    // Put seeds in flower pots
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
    while (!done && cycles < 15) {      // Wait 15 cycles, which should be enough time for the bees to do their thing
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

      // Check for fruit
      val fruits = Random.shuffle(getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[Fruit]().toList.sortBy(_.uuid))
      if (fruits.size > 0) {
        breakable {
          for (fruit <- fruits) {
            if (fruit.name.toLowerCase == seedType.toLowerCase) {
              // Found fruit
              runAction("focus on " + PathFinder.getObjUniqueReferent(fruit, getCurrentAgentLocation(runner)).get, runner)

              // In case it's ambiguous (hacky, but there is some non-determinism in here somewhere, possibly with the stochastic bees).
              if (runner.currentHistory.historyActions.last != "0") {
                runAction("0", runner)
              }
              done = true
              break()
            }
          }
        }
      }

      for (j <- 0 until 5) {
        runAction("wait1", runner)
      }

      runAction("look around", runner)

      // Keep track of number of cycles, so we don't get stuck in an infinite loop if conditions aren't met.
      cycles += 1
    }


    // Wait one moment
    runAction("wait1", runner)

    // Return
    return (true, getActionHistory(runner))
  }


  def mkGoldActionSequenceGrowPlant(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String]) = {
    val universe = runner.agentInterface.get.universe
    val agent = runner.agentInterface.get.agent

    // Task variables
    val seedType = this.getTaskValueStr(modifiers, "seedType").get
    val seedLocation = this.getTaskValueStr(modifiers, "location").get
    val containerNames = this.getTaskValueStr(modifiers, "containerNames").get.split(",")


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

    // Go to greenhouse
    val (actions1, actionStrs1) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = "greenhouse")
    runActionSequence(actionStrs1, runner)

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


    // See what the soil situation is like
    val soilInRoom = getCurrentAgentLocation(runner).getContainedObjectsOfType[Soil]().toArray

    // Case 1: Flower pot already exists with soil inside
    if (flowerPotsWithSoil.size > 0) {
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
        var agentHasShovel:Boolean = false
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


    // Get reference to a valid flower pot we can use
    val flowerpot = flowerPotsWithSoil(0)

    // Move seed to flower pot
    val seedName = seedType + " seed in seed jar"
    TaskParametric.runAction("move " + seedName + " to " + PathFinder.getObjUniqueReferent(flowerpot, TaskParametric.getCurrentAgentLocation(runner)).get, runner)
    //TaskParametric.runAction("0", runner)   // Ambiguity resolution

    // Get reference to seed
    val seed = flowerpot.getContainedAccessibleObjectsOfType[LivingThing]().toList(0)

    // Step N: Focus on seed
    val seedName1 = seedType + " seed in " + flowerpot.name
    runAction("focus on " + seedName1, runner)


    // TODO: Do watering
    // Pick up water jug
    val waterJug = getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[Jug]().toList.head
    val sink = getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[Sink]().toList.head


    // Watering cycle
    for (i <- 0 until 5) {
      // Turn on sink
      runAction("activate " + PathFinder.getObjUniqueReferent(sink, getCurrentAgentLocation(runner)).get, runner)

      // Water plant
      runAction("move " + PathFinder.getObjUniqueReferent(waterJug, getCurrentAgentLocation(runner)).get + " to " + PathFinder.getObjUniqueReferent(sink, getCurrentAgentLocation(runner)).get, runner)
      runAction("pour " + PathFinder.getObjUniqueReferent(waterJug, getCurrentAgentLocation(runner)).get + " into " + PathFinder.getObjUniqueReferent(flowerpot, getCurrentAgentLocation(runner)).get, runner)

      // Turn off sink
      runAction("deactivate " + PathFinder.getObjUniqueReferent(sink, getCurrentAgentLocation(runner)).get, runner)

      for (j <- 0 until 5) {
        runAction("wait1", runner)
      }
      runAction("look around", runner)
    }


    // Wait one moment
    runAction("wait1", runner)

    // Return
    return (true, getActionHistory(runner))
  }

}


object TaskGrowPlant {
  val MODE_GROW_PLANT       = "grow plant"
  val MODE_GROW_FRUIT       = "grow fruit"

  def registerTasks(taskMaker:TaskMaker1): Unit = {
    taskMaker.addTask( new TaskGrowPlant(mode = MODE_GROW_PLANT) )
    taskMaker.addTask( new TaskGrowPlant(mode = MODE_GROW_FRUIT) )
  }

  // Make a jar containing a number of seeds of the same type
  def mkSeedJar(plantType:String, numSeeds:Int = 5):EnvObject = {
    val jar = new CeramicCup()      // TODO, make jar
    jar.name = "seed jar"

    for (i <- 0 until numSeeds) {
      val seed = PlantReproduction.createSeed(plantType)
      if (seed.isDefined) jar.addObject(seed.get)
    }

    return jar
  }

  // Takes a seedJar as input, and determines what kind of seed is inside
  def getSeedType(seedJar:EnvObject): String = {
    val contents = seedJar.getContainedObjects()
    for (obj <- contents) {
      obj match {
        case x:Plant => return x.propLife.get.lifeformType
        case _ => { // do nothing
        }
      }
    }
    // We should never reach here
    return ""
  }

}
