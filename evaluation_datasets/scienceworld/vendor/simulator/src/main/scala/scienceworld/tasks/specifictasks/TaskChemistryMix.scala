package scienceworld.tasks.specifictasks

import scienceworld.actions.Action
import scienceworld.goldagent.PathFinder
import scienceworld.objects.agent.Agent
import scienceworld.objects.containers.{CeramicCup, Cup, FlowerPot, MetalPot}
import scienceworld.objects.document.{Paper, Recipe}
import scienceworld.objects.livingthing.plant.{Plant, Soil}
import scienceworld.objects.substance.food.{Almond, Apple, Banana, Bread, Cashew, Chocolate, Flour, Jam, Marshmallow, Orange, Peanut}
import scienceworld.objects.substance.paint.{BluePaint, GreenPaint, RedPaint}
import scienceworld.objects.substance.{AceticAcid, IronBlock, Soap, SodiumBicarbonate, SodiumChloride, Sugar, Water}
import scienceworld.processes.PlantReproduction
import scienceworld.processes.lifestage.PlantLifeStages.{PLANT_STAGE_ADULT_PLANT, PLANT_STAGE_REPRODUCING, PLANT_STAGE_SEED, PLANT_STAGE_SEEDLING}
import scienceworld.runtime.pythonapi.PythonInterface
import scienceworld.struct.EnvObject
import scienceworld.tasks.{Task, TaskMaker1, TaskModifier, TaskObject, TaskValueStr}
import scienceworld.tasks.goals.{Goal, GoalSequence}
import scienceworld.tasks.goals.specificgoals.{GoalFind, GoalInRoomWithObject, GoalLifeStage, GoalMoveToNewLocation, GoalObjectsInSingleContainer, GoalPastActionExamineObject, GoalPastActionReadObject}
import scienceworld.tasks.specifictasks.TaskChemistryMix.MODE_CHEMISTRY_MIX
import scienceworld.tasks.specifictasks.TaskFindLivingNonLiving.MODE_LIVING

import scala.collection.mutable.ArrayBuffer
import scala.util.control.Breaks.{break, breakable}

class TaskChemistryMix(val mode:String = MODE_LIVING) extends TaskParametric {
  val taskName = mode.replaceAll(" ", "-").replaceAll("[()]", "")


  // Variation 1: Which seeds to grow
  val baseChemicals = new ArrayBuffer[ Array[TaskModifier] ]()
  val locations = Array("kitchen", "workshop")

  // Train
  for (location <- locations) {
    // Salt + water = salt water
    val salt = new SodiumChloride()
    baseChemicals.append(TaskChemistryMix.setupRecipeTask(resultObject = "salt water", inputObjects = Array(salt, new Water()), generateLocation = location, excludeFromAdding = Array("water")))

    // Soap + water = soapy water
    val soap = new Soap()
    baseChemicals.append(TaskChemistryMix.setupRecipeTask(resultObject = "soapy water", inputObjects = Array(soap, new Water()), generateLocation = location, excludeFromAdding = Array("water")))

    // Mixed nuts
    val peanut = new Peanut()
    val almond = new Almond()
    val cashew = new Cashew()
    baseChemicals.append(TaskChemistryMix.setupRecipeTask(resultObject = "mixed nuts", inputObjects = Array(peanut, almond, cashew), generateLocation = location, excludeFromAdding = Array("water")))

    // Volcano
    val vinegar = new AceticAcid()
    val bakingsoda = new SodiumBicarbonate()
    baseChemicals.append(TaskChemistryMix.setupRecipeTask(resultObject = "sodium acetate", inputObjects = Array(vinegar, bakingsoda), generateLocation = location, excludeFromAdding = Array("water")))

    // banana + bread = banana sandwich
    baseChemicals.append(TaskChemistryMix.setupRecipeTask(resultObject = "banana sandwich", inputObjects = Array(new Banana(), new Bread()), generateLocation = location))

    // Paper + blue paint = blue paper  (paint should be found in art room)
    val paper1 = new Paper()
    val bluepaint = new BluePaint()
    baseChemicals.append(TaskChemistryMix.setupRecipeTask(resultObject = "blue paper", inputObjects = Array(paper1, bluepaint), generateLocation = location, excludeFromAdding = Array(bluepaint.name)))

    // peanut + bread = peanut butter sandwich
    baseChemicals.append(TaskChemistryMix.setupRecipeTask(resultObject = "peanut butter sandwich", inputObjects = Array(new Peanut(), new Bread()), generateLocation = location))

    // peanut + jam + bread = peanut butter with jam sandwich
    baseChemicals.append(TaskChemistryMix.setupRecipeTask(resultObject = "peanut butter with jam sandwich", inputObjects = Array(new Peanut(), new Jam(), new Bread()), generateLocation = location))
  }

  // Dev
  for (location <- locations) {
    // chocolate + marshmallow = smores
    val chocolate = new Chocolate()
    val marshmallow = new Marshmallow()
    baseChemicals.append(TaskChemistryMix.setupRecipeTask(resultObject = "smores", inputObjects = Array(chocolate, marshmallow), generateLocation = location))

    // Flour + water = dough
    val flour = new Flour()
    baseChemicals.append(TaskChemistryMix.setupRecipeTask(resultObject = "dough", inputObjects = Array(flour, new Water()), generateLocation = location, excludeFromAdding = Array("water")))

    // Apple + Orange + Banana
    val apple = new Apple()
    val orange = new Orange()
    val banana = new Banana()
    baseChemicals.append(TaskChemistryMix.setupRecipeTask(resultObject = "fruit salad", inputObjects = Array(apple, orange, banana), generateLocation = location))

    // jam + bread = peanut butter with jam sandwich
    baseChemicals.append(TaskChemistryMix.setupRecipeTask(resultObject = "jam sandwich", inputObjects = Array(new Jam(), new Bread()), generateLocation = location))
  }

  // Test
  for (location <- locations) {
    // sugar + water = sugar water
    val sugar = new Sugar()
    baseChemicals.append( TaskChemistryMix.setupRecipeTask(resultObject = "sugar water", inputObjects = Array(sugar, new Water()), generateLocation = location, excludeFromAdding = Array("water")) )

    // peanut + banana + bread = banana sandwich
    baseChemicals.append( TaskChemistryMix.setupRecipeTask(resultObject = "peanut butter with banana sandwich", inputObjects = Array(new Peanut(), new Banana(), new Bread()), generateLocation = location) )

    // Iron + water = rusty iron
    val ironblock = new IronBlock()
    baseChemicals.append( TaskChemistryMix.setupRecipeTask(resultObject = "rust", inputObjects = Array(ironblock, new Water()), generateLocation = location, excludeFromAdding = Array("water")) )

    // Paper + green paint = green paper  (paint should be found in art room)
    val paper2 = new Paper()
    val redpaint = new RedPaint()
    baseChemicals.append( TaskChemistryMix.setupRecipeTask(resultObject = "red paper", inputObjects = Array(paper2, redpaint), generateLocation = location, excludeFromAdding = Array(redpaint.name)) )
  }



  // Combinations
  val combinations = for {
    i <- baseChemicals
  } yield List(i)

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
    val resultChemical = this.getTaskValueStr(modifiers, key = "result")
    if (resultChemical.isEmpty) throw new RuntimeException("ERROR: Failed to find resultant chemical in task setup.")
    val inputChemicals = this.getTaskValueStr(modifiers, key = "inputChemicals").get.split(",")
    val location = this.getTaskValueStr(modifiers, key = "location")

    var subTask = ""
    val gSequence = new ArrayBuffer[Goal]
    val gSequenceUnordered = new ArrayBuffer[Goal]

    var description:String = "<empty>"
    if (mode == MODE_CHEMISTRY_MIX) {
      gSequence.append( new GoalFind(objectName = resultChemical.get, failIfWrong = true, description = "focus on result chemical (" + resultChemical.get + ")") )

      gSequenceUnordered.append(new GoalMoveToNewLocation(_isOptional = true, unlessInLocation = "", description = "move to a new location") )            // Move to any new location

      for (inputChemical <- inputChemicals) {
        gSequenceUnordered.append(new GoalInRoomWithObject(objectName = inputChemical, _isOptional = true, description = "be in same location as " + inputChemical))
      }
      gSequenceUnordered.append(new GoalObjectsInSingleContainer(objectNames = inputChemicals, _isOptional = true, description = "have all ingredients alone in a single container"))
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = resultChemical.get, _isOptional = true, description = "be in same location as " + resultChemical.get))
      gSequenceUnordered.append(new GoalPastActionReadObject(documentName = "recipe", _isOptional = true, description = "read recipe"))


      description = "Your task is to use chemistry to create the substance '" + resultChemical.get + "'. "
      description += "A recipe and some of the ingredients might be found near the " + location.get + ". "
      description += "When you are done, focus on the " + resultChemical.get + "."

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
    if (mode == MODE_CHEMISTRY_MIX) {
      return mkGoldActionSequenceChemistryMix(modifiers, runner)
    } else {
      throw new RuntimeException("ERROR: Unrecognized task mode: " + mode)
    }
  }


  def mkGoldActionSequenceChemistryMix(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String]) = {
    val universe = runner.agentInterface.get.universe
    val agent = runner.agentInterface.get.agent

    // Task variables
    val resultChemical = this.getTaskValueStr(modifiers, key = "result").get
    val inputChemicals = this.getTaskValueStr(modifiers, key = "inputChemicals").get.split(",")
    val location = this.getTaskValueStr(modifiers, key = "location").get


    // Step 1: Take a container (metal pot)
    val (actions1, actionStrs1) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = "kitchen")
    runActionSequence(actionStrs1, runner)

    runAction("open cupboard", runner)

    val containers = getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[Cup]().toList
    val containersEmpty = containers.filter(_.getContainedObjects(includeHidden = false).size == 0)
    val container = containersEmpty(0)

    runAction("pick up " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)


    // Stage 1: Get recipe
    // Move from starting location to get recipe (thermometer)
    val (actions, actionStrs) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = location)
    runActionSequence(actionStrs, runner)

    // Look around
    runAction("look around", runner)

    // Take recipe
    val recipes = PathFinder.getAllAccessibleEnvObject(queryName = "recipe", getCurrentAgentLocation(runner))
    if (recipes.length == 0) return (false, getActionHistory(runner))
    val recipe = recipes(0)
    //runAction("pick up " + PathFinder.getObjUniqueReferent(seedJar, getCurrentAgentLocation(runner)).get, runner)
    runAction("pick up " + recipe.name, runner)

    // Read recipe
    runAction("read " + "recipe in inventory", runner)

    // Focus on instrument
    //runAction("focus on " + instrument.name + " in inventory", runner)

    // Stage 2: Get task object
    // Go to task location
    /*
    val (actions1, actionStrs1) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = objectLocation)
    runActionSequence(actionStrs1, runner)
     */

    // Look around
    runAction("look around", runner)

    // Check to make sure the task object is available in an accessible container
    for (inputChemical <- inputChemicals) {
      //## runAction("NOTE: SEARCHING FOR INPUT CHEMICAL (" + inputChemical + ")", runner)
      var taskObject: EnvObject = null

      if (inputChemical == "water") {
        // Attempt to find water
        var (success, waterContainer, waterRef) = PathFinder.getWaterInContainer(runner, useInventoryContainer = Some(container))

        if (!success) {
          //## runAction("NOTE: WAS NOT ABLE TO FIND WATER", runner)

          // Try searching elsewhere
          val actionStrsSearchPattern1 = PathFinder.createActionSequenceSearchPatternPrecomputed(universe, agent, getCurrentAgentLocation(runner).name)

          // Walk around the environment until we find the thing to test
          breakable {
            for (searchPatternStep <- actionStrsSearchPattern1) {
              // First, check to see if the object is here
              val (success1, waterContainer1, waterRef1) = PathFinder.getWaterInContainer(runner, useInventoryContainer = Some(container))
              if (success1) {
                taskObject = waterRef1.get
                break()
              }

              // If not found, move to next location to continue search
              runActionSequence(searchPatternStep, runner)
              runAction("look around", runner)
            }

            val (success1, waterContainer1, waterRef1) = PathFinder.getWaterInContainer(runner, useInventoryContainer = Some(container))
            if (!success1) {
              //## runAction("NOTE: WAS NOT ABLE TO FIND WATER", runner)
              return (false, getActionHistory(runner))
            }
            taskObject = waterRef1.get
          }

        } else {
          taskObject = waterRef.get
        }

      } else {

        var successOpeningContainers: Boolean = true
        var substances: Array[EnvObject] = Array.empty[EnvObject]
        breakable {
          for (i <- 0 to 5) {
            println("*** FIND SUBSTANCE ATTEMPT " + i)
            substances = PathFinder.getAllAccessibleEnvObject(inputChemical, getCurrentAgentLocation(runner))
            if (substances.size > 0) break // Found at least one substance matching the criteria
            // If we reach here, we didn't find a substance -- start opening closed containers
            if (successOpeningContainers) {
              successOpeningContainers = PathFinder.openRandomClosedContainer(currentLocation = getCurrentAgentLocation(runner), runner)
            } else {
              // No more containers to open
              break()
            }
          }
        }

        // Pick up the task object
        var objects = PathFinder.getAllAccessibleEnvObject(queryName = inputChemical, getCurrentAgentLocation(runner))
        if (objects.length == 0) {

          // Try searching elsewhere
          val actionStrsSearchPattern1 = PathFinder.createActionSequenceSearchPatternPrecomputed(universe, agent, getCurrentAgentLocation(runner).name)

          // Walk around the environment until we find the thing to test
          breakable {
            for (searchPatternStep <- actionStrsSearchPattern1) {
              // First, check to see if the object is here
              val curLocSearch = PathFinder.getEnvObject(queryName = getCurrentAgentLocation(runner).name, universe) // Get a pointer to the whole room the answer box is in
              objects = PathFinder.getAllAccessibleEnvObject(queryName = inputChemical, getCurrentAgentLocation(runner))
              if (objects.size > 0) {
                //## runAction("NOTE: SEE INPUT CHEMICAL (" + inputChemical + ")", runner)
                break()
              } else {
                //## runAction("NOTE: DO NOT SEE INPUT CHEMICAL (" + inputChemical + ")", runner)
              }

              // If not found, move to next location to continue search
              runActionSequence(searchPatternStep, runner)
              runAction("look around", runner)
            }

            val curLocSearch = PathFinder.getEnvObject(queryName = getCurrentAgentLocation(runner).name, universe) // Get a pointer to the whole room the answer box is in
            objects = PathFinder.getAllAccessibleEnvObject(queryName = inputChemical, getCurrentAgentLocation(runner))

          }


          if (objects.length == 0) {
            //## runAction("NOTE: WAS NOT ABLE TO FIND SUBSTANCE (" + inputChemical + ")", runner)
            return (false, getActionHistory(runner))
          } else {
            taskObject = objects(0)
          }
        }

        // Pick up the object
        if (taskObject == null) {
          taskObject = objects(0)
        }

        if ((taskObject.propMaterial.isEmpty) || (taskObject.propMaterial.get.stateOfMatter == "solid")) {
          runAction("pick up " + PathFinder.getObjUniqueReferent(taskObject, getCurrentAgentLocation(runner)).get, runner)
          runAction("move " + PathFinder.getObjUniqueReferent(taskObject, getCurrentAgentLocation(runner)).get + " to " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)
        } else {
          runAction("pick up " + PathFinder.getObjUniqueReferent(taskObject.getContainer().get, getCurrentAgentLocation(runner)).get, runner)
        }


      }

      // Check it was picked up correctly
      if (PathFinder.getObjUniqueReferent(taskObject, getCurrentAgentLocation(runner)).isEmpty) {
        //## runAction("NOTE: CAN'T FIND THE OBJECT", runner)
        return (false, getActionHistory(runner))
      }

      // If it's a liquid, pour it into the main mixing container
      if ((taskObject.propMaterial.isDefined) && (taskObject.propMaterial.get.stateOfMatter == "liquid")) {
        // TODO: Needs proper referents
        runAction("pour " + PathFinder.getObjUniqueReferent(taskObject.getContainer().get, getCurrentAgentLocation(runner)).get + " into " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)
      }

    }


    // Do mixing
    runAction("examine " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)
    runAction("mix " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)

    // Focus on task result
    val resultChemicals = PathFinder.getAllAccessibleEnvObject(resultChemical, container)
    if (resultChemicals.size == 0) {
      //## runAction("NOTE: CAN'T FIND RESULT CHEMICAL", runner)
      return (false, getActionHistory(runner))
    }
    val result:EnvObject = resultChemicals(0)
    runAction("focus on " + PathFinder.getObjUniqueReferent(result, getCurrentAgentLocation(runner)).get, runner)


    // Wait one moment
    runAction("wait1", runner)

    //## debug, add subgoals
    //runAction(runner.agentInterface.get.getGoalProgressStr(), runner)

    // Return
    return (true, getActionHistory(runner))
  }


}


object TaskChemistryMix {
  val MODE_CHEMISTRY_MIX       = "chemistry mix"

  def registerTasks(taskMaker:TaskMaker1): Unit = {
    taskMaker.addTask( new TaskChemistryMix(mode = MODE_CHEMISTRY_MIX) )
  }


  // Create task modifiers for adding the objects, adding a recipe, and including task keys
  def setupRecipeTask(resultObject:String, inputObjects:Array[EnvObject], generateLocation:String, excludeFromAdding:Array[String] = Array.empty[String]):Array[TaskModifier] = {
    val out = new ArrayBuffer[TaskModifier]

    // Add objects
    for (inputObject <- inputObjects) {
      if (!excludeFromAdding.contains(inputObject.name) ) {
        out.append(new TaskObject(inputObject.name, Some(inputObject), roomToGenerateIn = generateLocation, Array.empty[String], generateNear = 0))
      }
    }

    // Keys
    out.append( new TaskValueStr(key = "inputChemicals", value = inputObjects.map(_.name).toArray.mkString(",")) )
    out.append( new TaskValueStr(key = "result", value = resultObject) )
    out.append( new TaskValueStr(key = "location", value = generateLocation) )

    // Add recipe
    val recipe = Recipe.mkRecipe(resultObject, thingsToMix = inputObjects.map(_.name))
    out.append(new TaskObject(recipe.name, Some(recipe), roomToGenerateIn = generateLocation, Array.empty[String], generateNear = 0))

    out.toArray
  }

}
