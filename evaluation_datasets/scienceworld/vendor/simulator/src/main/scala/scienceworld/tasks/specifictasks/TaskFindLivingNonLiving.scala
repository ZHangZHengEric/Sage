package scienceworld.tasks.specifictasks

import scienceworld.actions.Action
import scienceworld.environments.ContainerMaker
import scienceworld.goldagent.PathFinder
import scienceworld.objects.agent.Agent
import scienceworld.objects.containers.FlowerPot
import scienceworld.objects.devices.Stove
import scienceworld.objects.livingthing.animals.{Animal, Beaver, BlueJay, BrownBear, Butterfly, Crocodile, Dove, Elephant, Frog, GiantTortoise, Moth, Parrot, Toad, Turtle, Wolf}
import scienceworld.objects.livingthing.plant.{AppleTree, AvocadoTree, BananaTree, CherryTree, LemonTree, OrangeTree, PeaPlant, PeachTree, Plant, Soil}
import scienceworld.objects.taskitems.AnswerBox
import scienceworld.processes.lifestage.PlantLifeStages
import scienceworld.properties.LeadProp
import scienceworld.runtime.pythonapi.PythonInterface
import scienceworld.struct.EnvObject
import scienceworld.tasks.{Task, TaskDisable, TaskMaker1, TaskModifier, TaskObject, TaskValueStr}
import scienceworld.tasks.goals.{Goal, GoalSequence}
import scienceworld.tasks.goals.specificgoals.{GoalChangeStateOfMatter, GoalFocusOnAnimal, GoalFocusOnLivingThing, GoalFocusOnNonlivingThing, GoalFocusOnPlant, GoalInRoomWithOpenDoor, GoalIsDifferentStateOfMatter, GoalIsNotStateOfMatter, GoalIsStateOfMatter, GoalMoveToLocation, GoalMoveToNewLocation, GoalObjectInContainer}
import scienceworld.tasks.specifictasks.TaskChangeOfState.{MODE_BOIL, MODE_CHANGESTATE, MODE_FREEZE, MODE_MELT}
import scienceworld.tasks.specifictasks.TaskFindLivingNonLiving.{MODE_ANIMAL, MODE_LIVING, MODE_NONLIVING, MODE_PLANT}

import scala.collection.mutable.ArrayBuffer
import scala.util.Random
import scala.util.control.Breaks.{break, breakable}


class TaskFindLivingNonLiving(val mode:String = MODE_LIVING) extends TaskParametric {
  val taskName = mode.replaceAll(" ", "-").replaceAll("[()]", "")

  // Variation 1: Animals
  val livingThings = new ArrayBuffer[ Array[TaskModifier] ]()
  for (i <- 0 until 10) {
    val livingThingsToAdd = TaskFindLivingNonLiving.mkRandomAnimals(location = "outside", numAnimals = 3, variationIdx = i) ++
                            TaskFindLivingNonLiving.mkRandomPlants(location = "greenhouse", numPlants = 3, variationIdx = i)
    livingThings.append( livingThingsToAdd )
  }


  // Variation 2: Answer box possibilities
  val answerBoxPossibilities = new ArrayBuffer[ Array[TaskModifier] ]()
  val colours = Array("red", "green", "blue", "orange", "yellow", "purple")
  val locations = Array("kitchen", "bathroom", "living room", "bedroom", "workshop")
  for (location <- locations) {
    for (colour <- colours) {
      val answerBox = new AnswerBox(colour)
      answerBoxPossibilities.append(Array(new TaskObject(answerBox.name, Some(answerBox), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
        new TaskValueStr("location", location),
        new TaskValueStr("answerBox", answerBox.name)
      ))
    }
  }

  // Combinations
  val combinations = for {
    i <- livingThings
    j <- answerBoxPossibilities
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
    // Step 1: Find substance name
    val answerBoxName = this.getTaskValueStr(modifiers, "answerBox")
    val answerBoxLocation = this.getTaskValueStr(modifiers, "location")

    var subTask = ""
    val gSequence = new ArrayBuffer[Goal]
    val gSequenceUnordered = new ArrayBuffer[Goal]
    if (mode == MODE_LIVING) {
      subTask = "living thing"
      gSequence.append( new GoalFocusOnLivingThing(description = "focus on a living thing") )                                // Focus on a living thing
      gSequence.append( new GoalObjectInContainer(answerBoxName.get, description = "move living thing to answer box") )      // Move it into the answer box

      gSequenceUnordered.append( new GoalObjectInContainer("inventory", description = "Pick up object") )             // Put object in inventory
      gSequenceUnordered.append( new GoalInRoomWithOpenDoor(_isOptional = true, description = "Be in a room with an open door") )   // In a room with an open door
      gSequenceUnordered.append( new GoalMoveToNewLocation(_isOptional = true, description = "Move to a new location") )            // Move to any new location
      gSequenceUnordered.append( new GoalMoveToLocation(answerBoxLocation.get, _isOptional = true, description = "Move to the location of the answer box") )     // Move to answer box location
    } else if (mode == MODE_NONLIVING) {
      subTask = "non-living thing"
      gSequence.append( new GoalFocusOnNonlivingThing(description = "focus on a non-living thing") )                         // Focus on a non-living thing
      gSequence.append( new GoalObjectInContainer(answerBoxName.get, description = "move living thing to answer box") )      // Move it into the answer box

      gSequenceUnordered.append( new GoalObjectInContainer("inventory", description = "Pick up object") )             // Put object in inventory
      gSequenceUnordered.append( new GoalInRoomWithOpenDoor(_isOptional = true, description = "Be in a room with an open door") )   // In a room with an open door
      gSequenceUnordered.append( new GoalMoveToNewLocation(_isOptional = true, description = "Move to a new location") )            // Move to any new location
      gSequenceUnordered.append( new GoalMoveToLocation(answerBoxLocation.get, _isOptional = true, description = "Move to the location of the answer box") )     // Move to answer box location
    } else if (mode == MODE_PLANT) {
      subTask = "plant"
      gSequence.append( new GoalFocusOnPlant(description = "focus on a plant") )                                             // Focus on a plant
      gSequence.append( new GoalObjectInContainer(answerBoxName.get, description = "move living thing to answer box") )      // Move it into the answer box

      gSequenceUnordered.append( new GoalObjectInContainer("inventory", description = "Pick up object") )             // Put object in inventory
      gSequenceUnordered.append( new GoalInRoomWithOpenDoor(_isOptional = true, description = "Be in a room with an open door") )   // In a room with an open door
      gSequenceUnordered.append( new GoalMoveToNewLocation(_isOptional = true, description = "Move to a new location") )            // Move to any new location
      gSequenceUnordered.append( new GoalMoveToLocation(answerBoxLocation.get, _isOptional = true, description = "Move to the location of the answer box") )     // Move to answer box location
    } else if (mode == MODE_ANIMAL) {
      subTask = "animal"
      gSequence.append( new GoalFocusOnAnimal(description = "focus on an animal") )                                          // Focus on an animal
      gSequence.append( new GoalObjectInContainer(answerBoxName.get, description = "move living thing to answer box") )      // Move it into the answer box

      gSequenceUnordered.append( new GoalObjectInContainer("inventory", description = "Pick up object") )             // Put object in inventory
      gSequenceUnordered.append( new GoalInRoomWithOpenDoor(_isOptional = true, description = "Be in a room with an open door") )   // In a room with an open door
      gSequenceUnordered.append( new GoalMoveToNewLocation(_isOptional = true, description = "Move to a new location") )            // Move to any new location
      gSequenceUnordered.append( new GoalMoveToLocation(answerBoxLocation.get, _isOptional = true, description = "Move to the location of the answer box") )     // Move to answer box location
    } else {
      throw new RuntimeException("ERROR: Unrecognized task mode: " + mode)
    }

    val taskLabel = taskName + "-variation" + combinationNum
    val description = "Your task is to find a(n) " + subTask + ". First, focus on the thing. Then, move it to the " + answerBoxName.get + " in the " + answerBoxLocation.get + "."
    val goalSequence = new GoalSequence(gSequence.toArray, gSequenceUnordered.toArray)

    val task = new Task(taskName, description, goalSequence, taskModifiers = modifiers)

    // Return
    return task
  }

  def setupGoals(combinationNum:Int): Task = {
    this.setupGoals( this.getCombination(combinationNum), combinationNum )
  }

  def mkGoldActionSequence(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String]) = {
    if (mode == MODE_LIVING) {
      return mkGoldActionSequenceLiving(modifiers, runner)
    } else if (mode == MODE_NONLIVING) {
      return mkGoldActionSequenceNonLiving(modifiers, runner)
    } else if (mode == MODE_PLANT) {
      return mkGoldActionSequenceLiving(modifiers, runner)
    } else if (mode == MODE_ANIMAL) {
      return mkGoldActionSequenceLiving(modifiers, runner)
    } else {
      throw new RuntimeException("ERROR: Unrecognized task mode: " + mode)
    }

  }

  /*
   * Gold action sequences
   */
  def mkGoldActionSequenceNonLiving(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String]) = {
    // TODO: Unimplemented
    val answerBoxName = this.getTaskValueStr(modifiers, "answerBox").get
    val answerBoxLocation = this.getTaskValueStr(modifiers, "location").get

    val universe = runner.agentInterface.get.universe
    val agent = runner.agentInterface.get.agent


    // Step 1: Move from starting location to answer box location
    val startLocation = agent.getContainer().get.name
    val (actions, actionStrs) = PathFinder.createActionSequence(universe, agent, startLocation, endLocation = answerBoxLocation)
    runActionSequence(actionStrs, runner)

    // Step 1A: Look around
    val (actionLook, actionLookStr) = PathFinder.actionLookAround(agent)
    runAction(actionLookStr, runner)

    // Step 2: Pick a random object
    val curLoc1 = PathFinder.getEnvObject(queryName = answerBoxLocation, universe)    // Get a pointer to the whole room the answer box is in
    val objsInRoom = curLoc1.get.getContainedObjectsRecursiveAccessible(includeHidden = false)

    var objToMove:Option[EnvObject] = None
    breakable {
      for (obj <- Random.shuffle(objsInRoom.toList)) {
        if ((obj.propMoveable.isDefined) && (obj.propMoveable.get.isMovable == true)) {
          // Thing should not be answer box
          if (!obj.isInstanceOf[AnswerBox]) {
            if ((obj.propMaterial.isDefined) && (obj.propMaterial.get.stateOfMatter == "solid")) {

              // Thing should be non-living
              if (obj.propLife.isEmpty) {
                objToMove = Some(obj)
                break()
              }

            }
          }
        }
      }
    }

    // If we didn't find a movable object, we're in trouble -- quit
    if (objToMove.isEmpty) {
      return (false, getActionHistory(runner))
    }

    // Step 3: Focus on that random object
    val (actionFocus, actionFocusStr) = PathFinder.actionFocusOnObject(objToMove.get, agent, locationPerspective = curLoc1.get)
    // Add segment to path
    runAction(actionFocusStr, runner)

    // Step 4: Find answer box reference
    // TODO: Should just check for this object from base location
    val answerBox = PathFinder.getEnvObject(queryName = answerBoxName, universe)

    // Step 5: Move object to answer box
    val (actionMoveObj, actionMoveObjStr) = PathFinder.actionMoveObject(objToMove.get, answerBox.get, agent, locationPerspective = curLoc1.get)
    runAction(actionMoveObjStr, runner)


    // Return
    return (true, getActionHistory(runner))
  }


  def mkGoldActionSequenceLiving(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String]) = {
    // TODO: Unimplemented
    val answerBoxName = this.getTaskValueStr(modifiers, "answerBox").get
    val answerBoxLocation = this.getTaskValueStr(modifiers, "location").get

    val universe = runner.agentInterface.get.universe
    val agent = runner.agentInterface.get.agent


    var livingThingLocation = "outside"
    if (mode == MODE_LIVING) {
      val shuffledLocations = Random.shuffle(List("outside", "greenhouse"))
      livingThingLocation = shuffledLocations(0)
    } else if (mode == MODE_ANIMAL) {
      livingThingLocation = "outside"         // Animals are outside
    } else if (mode == MODE_PLANT) {
      livingThingLocation = "greenhouse"     // Plants are in the greenhouse
    }

    // Step 1: Move from starting location to a place likely to have animals
    val startLocation = agent.getContainer().get.name
    val (actions, actionStrs) = PathFinder.createActionSequence(universe, agent, startLocation, endLocation = livingThingLocation)
    runActionSequence(actionStrs, runner)

    // Step 1A: Look around
    val (actionLook, actionLookStr) = PathFinder.actionLookAround(agent)
    runAction(actionLookStr, runner)

    // Step 2: Pick a random object
    val curLoc1 = getCurrentAgentLocation(runner)
    val objsInRoom = curLoc1.getContainedObjectsRecursiveAccessible(includeHidden = false)

    var objToFocus:Option[EnvObject] = None
    var objToMove:Option[EnvObject] = None
    breakable {
      for (obj <- Random.shuffle(objsInRoom.toList)) {
        if ((obj.propMoveable.isDefined) && (obj.propMoveable.get.isMovable == true)) {

          if (obj.propLife.isDefined) {
            if (mode == MODE_LIVING) {
              if (obj.propLife.isDefined) {
                objToFocus = Some(obj)

                if (obj.isInstanceOf[Plant]) {
                  // For plants, pick up their containers (e.g. flower pots), or they'll die
                  if (obj.getContainer().get.isInstanceOf[FlowerPot]) {
                    objToMove = obj.getContainer()
                  } else {
                    // Back-off to picking up the actual plant, if needed
                    objToMove = Some(obj)
                  }
                } else {
                  // For animals, they can just be directly picked up
                  objToMove = Some(obj)
                }
                break()
              }
            } else if (mode == MODE_ANIMAL) {
              if (obj.isInstanceOf[Animal]) {
                objToFocus = Some(obj)
                objToMove = Some(obj)
                break()
              }
            } else if (mode == MODE_PLANT) {
              if (obj.isInstanceOf[Plant]) {
                objToFocus = Some(obj)

                // For plants, pick up their containers (e.g. flower pots), or they'll die
                if (obj.getContainer().get.isInstanceOf[FlowerPot]) {
                  objToMove = obj.getContainer()
                } else {
                  // Back-off to picking up the actual plant, if needed
                  objToMove = Some(obj)
                }
                break()
              }
            }
          }

        }
      }
    }

    // If we didn't find a movable object, we're in trouble -- quit
    if (objToMove.isEmpty) {
      return (false, getActionHistory(runner))
    }

    // Step 3: Focus on that random object
    val (actionFocus, actionFocusStr) = PathFinder.actionFocusOnObject(objToFocus.get, agent, locationPerspective = curLoc1)
    runAction(actionFocusStr, runner)

    // Step 4: Pick it up / place it in the inventory
    val (actionPickUp, actionPickUpStr) = PathFinder.actionPickUpObject(objToMove.get, agent, locationPerspective = curLoc1)
    runAction(actionPickUpStr, runner)

    // Step 5: Move from current location to answer box location
    val (actions1, actionStrs1) = PathFinder.createActionSequence(universe, agent, startLocation = livingThingLocation, endLocation = answerBoxLocation)
    runActionSequence(actionStrs1, runner)

    // Step 6: Find answer box reference
    // TODO: Should just check for this object from base location

    // Step 7: Move object to answer box
    val curLoc2 = PathFinder.getEnvObject(queryName = answerBoxLocation, universe)    // Get a pointer to the answer box location (should also be current location)
    val answerBox = PathFinder.getEnvObject(queryName = answerBoxName, curLoc2.get)   // Get a pointer to the answer box
    val (actionMoveObj, actionMoveObjStr) = PathFinder.actionMoveObjectFromInventory(objToMove.get, answerBox.get, agent, locationPerspective = curLoc2.get)
    runAction(actionMoveObjStr, runner)

    // Return
    return (true, getActionHistory(runner))
  }

}


object TaskFindLivingNonLiving {
  val MODE_LIVING       = "find living thing"
  val MODE_NONLIVING    = "find non-living thing"
  val MODE_PLANT        = "find plant"
  val MODE_ANIMAL       = "find animal"


  def registerTasks(taskMaker:TaskMaker1): Unit = {
    taskMaker.addTask( new TaskFindLivingNonLiving(mode = MODE_LIVING) )
    taskMaker.addTask( new TaskFindLivingNonLiving(mode = MODE_NONLIVING) )
    taskMaker.addTask( new TaskFindLivingNonLiving(mode = MODE_PLANT) )
    taskMaker.addTask( new TaskFindLivingNonLiving(mode = MODE_ANIMAL) )
  }


  // Randomly choose a set of N distractor animals to include in the environment
  def mkRandomAnimals(location:String, numAnimals:Int = 5, variationIdx:Int):Array[TaskModifier] = {
    val allAnimals = List(new Butterfly(), new Moth(), new Frog(), new Toad(), new GiantTortoise(), new Turtle(), new Crocodile(), new Parrot(), new Dove(), new BlueJay(), new Elephant(), new BrownBear(), new Beaver(), new Wolf() )
    val rand = new Random(variationIdx)     // Use variationIdx for seed
    // Shuffle
    val shuffled = rand.shuffle(allAnimals)

    val out = new ArrayBuffer[TaskModifier]
    for (i <- 0 until numAnimals) {
      val animal = shuffled(i)
      out.append( new TaskObject(animal.name, Some(animal), roomToGenerateIn = location, Array.empty[String], generateNear = 0) )
    }

    out.toArray
  }

  // Randomly choose a set of N distractor animals to include in the environment
  def mkRandomPlants(location:String, numPlants:Int = 5, variationIdx:Int):Array[TaskModifier] = {
    val allPlants = List(new AppleTree(), new AvocadoTree(), new BananaTree(), new CherryTree(), new LemonTree(), new OrangeTree(), new PeachTree(), new PeaPlant())

    val allPlantsInPots = new ArrayBuffer[EnvObject]

    val flowerPotIndices = Random.shuffle(List(1, 2, 3, 4, 5, 6, 7, 8, 9))
    for (i <- 0 until allPlants.size) {
      val plant = allPlants(i)

      val flowerpot = new FlowerPot()

      // Try to change the plant into an adult plant
      plant.lifecycle.get.changeStage(PlantLifeStages.PLANT_STAGE_ADULT_PLANT, failGracefully = true)

      flowerpot.addObject(plant)
      flowerpot.addObject(new Soil())
      allPlantsInPots.append(flowerpot)
    }

    val rand = new Random(variationIdx)     // Use variationIdx for seed
    // Shuffle
    val shuffled = rand.shuffle(allPlantsInPots)

    // Add a random selection of plants
    val out = new ArrayBuffer[TaskModifier]
    for (i <- 0 until numPlants) {
      val plantInPot = shuffled(i)
      plantInPot.name = "flower pot " + flowerPotIndices(i)
      out.append( new TaskObject(plantInPot.name, Some(plantInPot), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true) )
    }

    // Randomly add a few empty distractor flower pots, too
    for (i <- numPlants until numPlants + 2) {
      val flowerPot = new FlowerPot
      flowerPot.name = "flower pot " + flowerPotIndices(i)
      out.append( new TaskObject(flowerPot.name, Some(flowerPot), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true) )
    }

    out.toArray
  }


}
