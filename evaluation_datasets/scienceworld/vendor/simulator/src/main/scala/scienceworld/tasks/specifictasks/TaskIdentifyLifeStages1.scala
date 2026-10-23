package scienceworld.tasks.specifictasks

import scienceworld.actions.Action
import scienceworld.goldagent.PathFinder
import scienceworld.objects.agent.Agent
import scienceworld.objects.livingthing.LivingThing
import scienceworld.objects.livingthing.animals.{Ant, Beaver, BlueJay, BrownBear, Butterfly, Chameleon, Chipmunk, Crocodile, Dove, Dragonfly, Elephant, Frog, GiantTortoise, Hedgehog, Moth, Mouse, Parrot, Rabbit, Toad, Turtle, Wolf}
import scienceworld.objects.livingthing.plant.Plant
import scienceworld.runtime.pythonapi.PythonInterface
import scienceworld.struct.EnvObject
import scienceworld.tasks.{Task, TaskMaker1, TaskModifier, TaskObject, TaskValueStr}
import scienceworld.tasks.goals.{Goal, GoalSequence}
import scienceworld.tasks.goals.specificgoals.{GoalFind, GoalFindLivingThingStage, GoalMoveToLocation, GoalMoveToNewLocation, GoalStayInLocation}
import scienceworld.tasks.specifictasks.TaskIdentifyLifeStages1._

import scala.collection.mutable.ArrayBuffer
import scala.util.Random
import scala.util.control.Breaks._


class TaskIdentifyLifeStages1(val mode:String = MODE_LIFESTAGES) extends TaskParametric {
  val taskName = mode.replaceAll(" ", "-").replaceAll("[()]", "")

  val locations = Array("outside")

  // Variation 1: Which seeds to grow
  val numDistractors = 5
  val animalsAndStages = new ArrayBuffer[ Array[TaskModifier] ]()
  for (location <- locations) {
    animalsAndStages.append( TaskIdentifyLifeStages1.mkTaskVariation(livingThing = new Butterfly(), location = location) ++ TaskIdentifyLifeStages1.mkDistractorAnimals(location, numDistractors, 0))
    animalsAndStages.append( TaskIdentifyLifeStages1.mkTaskVariation(livingThing = new Moth(), location = location) ++ TaskIdentifyLifeStages1.mkDistractorAnimals(location, numDistractors, 1))

    animalsAndStages.append( TaskIdentifyLifeStages1.mkTaskVariation(livingThing = new Frog(), location = location) ++ TaskIdentifyLifeStages1.mkDistractorAnimals(location, numDistractors, 2))
    animalsAndStages.append( TaskIdentifyLifeStages1.mkTaskVariation(livingThing = new Toad(), location = location) ++ TaskIdentifyLifeStages1.mkDistractorAnimals(location, numDistractors, 3))

    animalsAndStages.append( TaskIdentifyLifeStages1.mkTaskVariation(livingThing = new GiantTortoise(), location = location) ++ TaskIdentifyLifeStages1.mkDistractorAnimals(location, numDistractors, 4))
    animalsAndStages.append( TaskIdentifyLifeStages1.mkTaskVariation(livingThing = new Turtle(), location = location) ++ TaskIdentifyLifeStages1.mkDistractorAnimals(location, numDistractors, 5))
    animalsAndStages.append( TaskIdentifyLifeStages1.mkTaskVariation(livingThing = new Crocodile(), location = location) ++ TaskIdentifyLifeStages1.mkDistractorAnimals(location, numDistractors, 6))

    animalsAndStages.append( TaskIdentifyLifeStages1.mkTaskVariation(livingThing = new Parrot(), location = location) ++ TaskIdentifyLifeStages1.mkDistractorAnimals(location, numDistractors, 7))
    animalsAndStages.append( TaskIdentifyLifeStages1.mkTaskVariation(livingThing = new Dove(), location = location) ++ TaskIdentifyLifeStages1.mkDistractorAnimals(location, numDistractors, 8))
    animalsAndStages.append( TaskIdentifyLifeStages1.mkTaskVariation(livingThing = new BlueJay(), location = location) ++ TaskIdentifyLifeStages1.mkDistractorAnimals(location, numDistractors, 9))

    animalsAndStages.append( TaskIdentifyLifeStages1.mkTaskVariation(livingThing = new Elephant(), location = location) ++ TaskIdentifyLifeStages1.mkDistractorAnimals(location, numDistractors, 10))
    animalsAndStages.append( TaskIdentifyLifeStages1.mkTaskVariation(livingThing = new BrownBear(), location = location) ++ TaskIdentifyLifeStages1.mkDistractorAnimals(location, numDistractors, 11))
    animalsAndStages.append( TaskIdentifyLifeStages1.mkTaskVariation(livingThing = new Beaver(), location = location) ++ TaskIdentifyLifeStages1.mkDistractorAnimals(location, numDistractors, 12))
    animalsAndStages.append( TaskIdentifyLifeStages1.mkTaskVariation(livingThing = new Wolf(), location = location) ++ TaskIdentifyLifeStages1.mkDistractorAnimals(location, numDistractors, 13))
  }

  // Repeatably shuffle order, so all of one type isn't in a given train/dev/test set
  val r = new scala.util.Random(1)
  val animalsAndStagesRandomized = r.shuffle(animalsAndStages.toList)

  // Combinations
  val combinations = for {
    i <- animalsAndStagesRandomized
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
    val animalName = this.getTaskValueStr(modifiers, "animal")
    if (animalName.isEmpty) throw new RuntimeException("ERROR: Failed to find animal name in task setup.")
    val stage1 = this.getTaskValueStr(modifiers, "stage1")
    if (stage1.isEmpty) throw new RuntimeException("ERROR: Failed to find lifecycle stage 1 in task setup.")
    val stage2 = this.getTaskValueStr(modifiers, "stage2")
    if (stage2.isEmpty) throw new RuntimeException("ERROR: Failed to find lifecycle stage 2 in task setup.")
    val stage3 = this.getTaskValueStr(modifiers, "stage3")
    //if (stage3.isEmpty) throw new RuntimeException("ERROR: Failed to find lifecycle stage 3 in task setup.")
    val stage4 = this.getTaskValueStr(modifiers, "stage4")
    //if (stage4.isEmpty) throw new RuntimeException("ERROR: Failed to find lifecycle stage 4 in task setup.")
    val stage5 = this.getTaskValueStr(modifiers, "stage5")
    //if (stage5.isEmpty) throw new RuntimeException("ERROR: Failed to find lifecycle stage 5 in task setup.")

    val animalLocation = this.getTaskValueStr(modifiers, "location")


    val gSequence = new ArrayBuffer[Goal]
    val gSequenceUnordered = new ArrayBuffer[Goal]
    var description:String = "<empty>"
    if (mode == MODE_LIFESTAGES) {

      gSequence.append(new GoalFindLivingThingStage(livingThingType = animalName.get, lifeStage = stage1.get, failIfWrong = true, _defocusOnSuccess = true, description = "focus on animal in life stage 1"))
      if (stage2.isDefined) gSequence.append(new GoalFindLivingThingStage(livingThingType = animalName.get, lifeStage = stage2.get, failIfWrong = true, _defocusOnSuccess = true, description = "focus on animal in life stage 2"))
      if (stage3.isDefined) gSequence.append(new GoalFindLivingThingStage(livingThingType = animalName.get, lifeStage = stage3.get, failIfWrong = true, _defocusOnSuccess = true, description = "focus on animal in life stage 3"))
      if (stage4.isDefined) gSequence.append(new GoalFindLivingThingStage(livingThingType = animalName.get, lifeStage = stage4.get, failIfWrong = true, _defocusOnSuccess = true, description = "focus on animal in life stage 4"))
      if (stage5.isDefined) gSequence.append(new GoalFindLivingThingStage(livingThingType = animalName.get, lifeStage = stage5.get, failIfWrong = true, _defocusOnSuccess = true, description = "focus on animal in life stage 5"))

      gSequenceUnordered.append( new GoalMoveToNewLocation(_isOptional = true, unlessInLocation = animalLocation.get, description = "Move to a new location (unless starting in task location)") )            // Move to any new location
      gSequenceUnordered.append( new GoalMoveToLocation(animalLocation.get, _isOptional = true, description = "Move to the location asked by the task") )
      gSequenceUnordered.append( new GoalStayInLocation(locationToBeIn = animalLocation.get, minSteps = 10, description = "Stay in goal location for 10 steps"))
      gSequenceUnordered.append( new GoalStayInLocation(locationToBeIn = animalLocation.get, minSteps = 20, description = "Stay in goal location for 20 steps"))
      gSequenceUnordered.append( new GoalStayInLocation(locationToBeIn = animalLocation.get, minSteps = 30, description = "Stay in goal location for 30 steps"))

      val numLifeStages = gSequence.length

      description = "Your task is to focus on the " + numLifeStages + " life stages of the " + animalName.get + ", starting from earliest to latest." // TODO: Better description?

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
    if (mode == MODE_LIFESTAGES) {
      return mkGoldActionSequenceLifeStages(modifiers, runner)
    } else {
      throw new RuntimeException("ERROR: Unrecognized task mode: " + mode)
    }

  }

  /*
   * Gold action sequences
   */
  def mkGoldActionSequenceLifeStages(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String]) = {
    val universe = runner.agentInterface.get.universe
    val agent = runner.agentInterface.get.agent

    // Task variables
    val animalName = this.getTaskValueStr(modifiers, "animal").get
    val animalLocation = this.getTaskValueStr(modifiers, "location").get
    val stage1 = this.getTaskValueStr(modifiers, "stage1")
    val stage2 = this.getTaskValueStr(modifiers, "stage2")
    val stage3 = this.getTaskValueStr(modifiers, "stage3")
    val stage4 = this.getTaskValueStr(modifiers, "stage4")
    val stage5 = this.getTaskValueStr(modifiers, "stage5")

    // Step 1: Move from starting location to task location
    val startLocation = agent.getContainer().get.name
    val (actions, actionStrs) = PathFinder.createActionSequence(universe, agent, startLocation, endLocation = animalLocation)
    runActionSequence(actionStrs, runner)

    // Look around
    runAction("look around", runner)

    // Stage 1
    if (stage1.isDefined) {
      val success = mkActionSequenceWaitForLivingThingInStage(stageName = stage1.get, livingThingName = animalName, runner)
      if (!success) return (false, getActionHistory(runner))
    }

    // Stage 2
    if (stage2.isDefined) {
      val success = mkActionSequenceWaitForLivingThingInStage(stageName = stage2.get, livingThingName = animalName, runner)
      if (!success) return (false, getActionHistory(runner))
    }

    // Stage 3
    if (stage3.isDefined) {
      val success = mkActionSequenceWaitForLivingThingInStage(stageName = stage3.get, livingThingName = animalName, runner)
      if (!success) return (false, getActionHistory(runner))
    }

    // Stage 4
    if (stage4.isDefined) {
      val success = mkActionSequenceWaitForLivingThingInStage(stageName = stage4.get, livingThingName = animalName, runner)
      if (!success) return (false, getActionHistory(runner))
    }

    // Stage 5
    if (stage5.isDefined) {
      val success = mkActionSequenceWaitForLivingThingInStage(stageName = stage5.get, livingThingName = animalName, runner)
      if (!success) return (false, getActionHistory(runner))
    }


    // Wait one moment
    runAction("wait1", runner)

    // Return
    return (true, getActionHistory(runner))
  }


}


object TaskIdentifyLifeStages1 {
  val MODE_LIFESTAGES       = "identify life stages 1"

  def registerTasks(taskMaker:TaskMaker1): Unit = {
    taskMaker.addTask( new TaskIdentifyLifeStages1(mode = MODE_LIFESTAGES) )
  }


  /*
   * Helper functions
   */

  // Randomly choose a set of N distractor animals to include in the environment
  def mkDistractorAnimals(location:String, numAnimals:Int = 5, variationIdx:Int):Array[TaskModifier] = {
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

  // Make a task variation that includes (a) adding the living thing to the environment, (b) recording it's life stages in key/value pairs in the task modifiers
  def mkTaskVariation(livingThing: LivingThing, location: String): Array[TaskModifier] = {

    // Get living thing life stages
    var lifestages = livingThing.lifecycle.get.stages.map(_.stageName)
    lifestages = lifestages.slice(0, lifestages.length - 1)               // Remove identifying the last life stage from the task, since it's usually always 'dead'
    val stageKeys = new ArrayBuffer[TaskModifier]
    for (i <- 0 until lifestages.length) {
      val lifestageName = lifestages(i)
      stageKeys.append(new TaskValueStr(key = "stage" + (i + 1), value = lifestageName))
      //## println("stage" + i + "\t" + lifestageName)
    }

    // Create task modifier
    val out = Array(new TaskObject(livingThing.name, Some(livingThing), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
                    new TaskValueStr(key = "animal", value = livingThing.name),
                    new TaskValueStr(key = "location", value = location)) ++ stageKeys

    return out
  }


  def mkActionSequenceWaitForLivingThingInStage(stageName:String, livingThingName:String, runner:PythonInterface, MAX_WAIT_TIME:Int = 20): Boolean = {
    val agentLocation = TaskParametric.getCurrentAgentLocation(runner)
    val livingThings = agentLocation.getContainedAccessibleObjectsOfType[LivingThing](includeHidden = false, includePortals = false).toArray
    var found: Option[LivingThing] = None
    breakable {
      for (i <- 0 until MAX_WAIT_TIME) {
        for (livingThing <- livingThings) {
          livingThing match {
            case lt: LivingThing => {
              // Check that it's the correct life form type
              if ((lt.propLife.isDefined) && (lt.propLife.get.lifeformType == livingThingName)) {
                // Check that it's in the correct life stage
                if (lt.lifecycle.get.getCurStageName() == stageName) {
                  found = Some(lt)
                  break()
                }
              }
            }
          }
        }
        // Not found -- wait one step, and check again
        TaskParametric.runAction("wait1", runner)
      }
    }

    // Check for failure
    if (found.isEmpty) return false

    //TaskParametric.runAction("focus on " + PathFinder.getObjUniqueReferent(found.get, TaskParametric.getCurrentAgentLocation(runner)).get, runner)
    val container = found.get.getContainer().get
    if (found.get.isInstanceOf[Plant]) {
      val referent = found.get.name + " in the " + stageName + " stage"
      TaskParametric.runAction("focus on " + referent + " in " + container.name, runner)
    } else {
      val referent = stageName + " " + found.get.name
      TaskParametric.runAction("focus on " + referent + " in " + container.name, runner)
    }

    TaskParametric.runAction("look around", runner)

    // Success
    return true
  }


}
