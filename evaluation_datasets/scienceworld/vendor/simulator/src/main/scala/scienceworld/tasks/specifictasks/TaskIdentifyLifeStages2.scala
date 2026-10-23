package scienceworld.tasks.specifictasks

import scienceworld.actions.Action
import scienceworld.goldagent.PathFinder
import scienceworld.objects.agent.Agent
import scienceworld.objects.containers.SelfWateringFlowerPot
import scienceworld.objects.containers.furniture.Cupboard
import scienceworld.objects.livingthing.LivingThing
import scienceworld.objects.livingthing.animals.{Ant, Beaver, BlueJay, BrownBear, Butterfly, Chameleon, Chipmunk, Crocodile, Dove, Dragonfly, Elephant, Frog, GiantTortoise, Hedgehog, Moth, Mouse, Parrot, Rabbit, Toad, Turtle, Wolf}
import scienceworld.objects.livingthing.plant.{AppleTree, ApricotTree, AvocadoTree, BananaTree, CherryTree, GrapefruitTree, LemonTree, OrangeTree, PeachTree, PearTree, Soil}
import scienceworld.runtime.pythonapi.PythonInterface
import scienceworld.struct.EnvObject
import scienceworld.tasks.{Task, TaskMaker1, TaskModifier, TaskObject, TaskValueStr}
import scienceworld.tasks.goals.{Goal, GoalSequence}
import scienceworld.tasks.goals.specificgoals.{GoalFind, GoalFindLivingThingStage, GoalMoveToLocation, GoalMoveToNewLocation, GoalStayInLocation}
import scienceworld.tasks.specifictasks.TaskIdentifyLifeStages1.mkActionSequenceWaitForLivingThingInStage
import scienceworld.tasks.specifictasks.TaskIdentifyLifeStages2._

import scala.collection.mutable.ArrayBuffer
import scala.util.Random

// TODO: CHANGE TO PLANTS INSTEAD OF ANIMALS?
class TaskIdentifyLifeStages2(val mode:String = MODE_LIFESTAGES) extends TaskParametric {
  val taskName = mode.replaceAll(" ", "-").replaceAll("[()]", "")

  val locations = Array("outside")

  // Variation 1: Which seeds to grow
  val numDistractors = 1

  val plantsAndStages = new ArrayBuffer[ Array[TaskModifier] ]()

  for (location <- locations) {
    plantsAndStages.append( TaskIdentifyLifeStages2.mkTaskVariation(livingThing = new AppleTree(), livingThingsToAdd = AppleTree.mkExamplesAtLifeStages(), location = location) ++ TaskIdentifyLifeStages2.mkDistractorAnimals(location, numDistractors, 0))
    plantsAndStages.append( TaskIdentifyLifeStages2.mkTaskVariation(livingThing = new ApricotTree(), livingThingsToAdd = ApricotTree.mkExamplesAtLifeStages(), location = location) ++ TaskIdentifyLifeStages2.mkDistractorAnimals(location, numDistractors, 6))
    plantsAndStages.append( TaskIdentifyLifeStages2.mkTaskVariation(livingThing = new AvocadoTree(), livingThingsToAdd = AvocadoTree.mkExamplesAtLifeStages(), location = location) ++ TaskIdentifyLifeStages2.mkDistractorAnimals(location, numDistractors, 1))
    plantsAndStages.append( TaskIdentifyLifeStages2.mkTaskVariation(livingThing = new BananaTree(), livingThingsToAdd = BananaTree.mkExamplesAtLifeStages(), location = location) ++ TaskIdentifyLifeStages2.mkDistractorAnimals(location, numDistractors, 2))
    plantsAndStages.append( TaskIdentifyLifeStages2.mkTaskVariation(livingThing = new CherryTree(), livingThingsToAdd = CherryTree.mkExamplesAtLifeStages(), location = location) ++ TaskIdentifyLifeStages2.mkDistractorAnimals(location, numDistractors, 3))
    plantsAndStages.append( TaskIdentifyLifeStages2.mkTaskVariation(livingThing = new GrapefruitTree(), livingThingsToAdd = GrapefruitTree.mkExamplesAtLifeStages(), location = location) ++ TaskIdentifyLifeStages2.mkDistractorAnimals(location, numDistractors, 6))
    plantsAndStages.append( TaskIdentifyLifeStages2.mkTaskVariation(livingThing = new LemonTree(), livingThingsToAdd = LemonTree.mkExamplesAtLifeStages(), location = location) ++ TaskIdentifyLifeStages2.mkDistractorAnimals(location, numDistractors, 4))
    plantsAndStages.append( TaskIdentifyLifeStages2.mkTaskVariation(livingThing = new OrangeTree(), livingThingsToAdd = OrangeTree.mkExamplesAtLifeStages(), location = location) ++ TaskIdentifyLifeStages2.mkDistractorAnimals(location, numDistractors, 5))
    plantsAndStages.append( TaskIdentifyLifeStages2.mkTaskVariation(livingThing = new PeachTree(), livingThingsToAdd = PeachTree.mkExamplesAtLifeStages(), location = location) ++ TaskIdentifyLifeStages2.mkDistractorAnimals(location, numDistractors, 6))
    plantsAndStages.append( TaskIdentifyLifeStages2.mkTaskVariation(livingThing = new PearTree(), livingThingsToAdd = PearTree.mkExamplesAtLifeStages(), location = location) ++ TaskIdentifyLifeStages2.mkDistractorAnimals(location, numDistractors, 6))
  }

  // Combinations
  val combinations = for {
    i <- plantsAndStages
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
    val livingThingName = this.getTaskValueStr(modifiers, "livingThingName")
    if (livingThingName.isEmpty) throw new RuntimeException("ERROR: Failed to find animal name in task setup.")
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

    val livingThingLocation = this.getTaskValueStr(modifiers, "location")

    val gSequence = new ArrayBuffer[Goal]
    val gSequenceUnordered = new ArrayBuffer[Goal]
    var description:String = "<empty>"
    if (mode == MODE_LIFESTAGES) {

      gSequence.append(new GoalFindLivingThingStage(livingThingType = livingThingName.get, lifeStage = stage1.get, failIfWrong = true, _defocusOnSuccess = true, description = "focus on plant in life stage 1"))
      if (stage2.isDefined) gSequence.append(new GoalFindLivingThingStage(livingThingType = livingThingName.get, lifeStage = stage2.get, failIfWrong = true, _defocusOnSuccess = true, description = "focus on plant in life stage 2"))
      if (stage3.isDefined) gSequence.append(new GoalFindLivingThingStage(livingThingType = livingThingName.get, lifeStage = stage3.get, failIfWrong = true, _defocusOnSuccess = true, description = "focus on plant in life stage 3"))
      if (stage4.isDefined) gSequence.append(new GoalFindLivingThingStage(livingThingType = livingThingName.get, lifeStage = stage4.get, failIfWrong = true, _defocusOnSuccess = true, description = "focus on plant in life stage 4"))
      if (stage5.isDefined) gSequence.append(new GoalFindLivingThingStage(livingThingType = livingThingName.get, lifeStage = stage5.get, failIfWrong = true, _defocusOnSuccess = true, description = "focus on plant in life stage 5"))

      // Unordered
      gSequenceUnordered.append( new GoalMoveToNewLocation(_isOptional = true, unlessInLocation = livingThingName.get, description = "Move to a new location (unless starting in task location)") )            // Move to any new location
      gSequenceUnordered.append( new GoalMoveToLocation(livingThingLocation.get, _isOptional = true, description = "Move to the location asked by the task") )
      gSequenceUnordered.append( new GoalStayInLocation(locationToBeIn = livingThingLocation.get, minSteps = 10, description = "Stay in goal location for 10 steps"))
      gSequenceUnordered.append( new GoalStayInLocation(locationToBeIn = livingThingLocation.get, minSteps = 20, description = "Stay in goal location for 20 steps"))
      gSequenceUnordered.append( new GoalStayInLocation(locationToBeIn = livingThingLocation.get, minSteps = 30, description = "Stay in goal location for 30 steps"))

      val numLifeStages = gSequence.length

      description = "Your task is to focus on the life stages of the " + livingThingName.get + " plant, starting from earliest to latest. The plants are located " + livingThingLocation.get + "." // TODO: Better description?

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
    val livingThingName = this.getTaskValueStr(modifiers, "livingThingName").get
    val livingThingLocation = this.getTaskValueStr(modifiers, "location").get
    val stage1 = this.getTaskValueStr(modifiers, "stage1")
    val stage2 = this.getTaskValueStr(modifiers, "stage2")
    val stage3 = this.getTaskValueStr(modifiers, "stage3")
    val stage4 = this.getTaskValueStr(modifiers, "stage4")
    val stage5 = this.getTaskValueStr(modifiers, "stage5")

    // Step 1: Move from starting location to task location
    val startLocation = agent.getContainer().get.name
    val (actions, actionStrs) = PathFinder.createActionSequence(universe, agent, startLocation, endLocation = livingThingLocation)
    runActionSequence(actionStrs, runner)

    // Look around
    runAction("look around", runner)

    // Stage 1
    if (stage1.isDefined) {
      val success = mkActionSequenceWaitForLivingThingInStage(stageName = stage1.get, livingThingName = livingThingName, runner)
      if (!success) return (false, getActionHistory(runner))
    }

    // Stage 2
    if (stage2.isDefined) {
      val success = mkActionSequenceWaitForLivingThingInStage(stageName = stage2.get, livingThingName = livingThingName, runner)
      if (!success) return (false, getActionHistory(runner))
    }

    // Stage 3
    if (stage3.isDefined) {
      val success = mkActionSequenceWaitForLivingThingInStage(stageName = stage3.get, livingThingName = livingThingName, runner)
      if (!success) return (false, getActionHistory(runner))
    }

    // Stage 4
    if (stage4.isDefined) {
      val success = mkActionSequenceWaitForLivingThingInStage(stageName = stage4.get, livingThingName = livingThingName, runner)
      if (!success) return (false, getActionHistory(runner))
    }

    // Stage 5
    if (stage5.isDefined) {
      val success = mkActionSequenceWaitForLivingThingInStage(stageName = stage5.get, livingThingName = livingThingName, runner)
      if (!success) return (false, getActionHistory(runner))
    }


    // Wait one moment
    runAction("wait1", runner)

    // Return
    return (true, getActionHistory(runner))
  }


}


object TaskIdentifyLifeStages2 {
  val MODE_LIFESTAGES       = "identify life stages 2"

  def registerTasks(taskMaker:TaskMaker1): Unit = {
    taskMaker.addTask( new TaskIdentifyLifeStages2(mode = MODE_LIFESTAGES) )
  }


  /*
   * Helper functions
   */

  // Randomly choose a set of N distractor animals to include in the environment
  // This version also instantiates the different life stages of those distractor animals.
  def mkDistractorAnimals(location:String, numAnimals:Int = 3, variationIdx:Int):Array[TaskModifier] = {
    val allAnimals = List(Butterfly.mkExamplesAtLifeStages(), Moth.mkExamplesAtLifeStages(), Frog.mkExamplesAtLifeStages(), Toad.mkExamplesAtLifeStages(), GiantTortoise.mkExamplesAtLifeStages(), Turtle.mkExamplesAtLifeStages(), Crocodile.mkExamplesAtLifeStages(), Parrot.mkExamplesAtLifeStages(), Dove.mkExamplesAtLifeStages(), BlueJay.mkExamplesAtLifeStages(), Elephant.mkExamplesAtLifeStages(), BrownBear.mkExamplesAtLifeStages(), Beaver.mkExamplesAtLifeStages(), Wolf.mkExamplesAtLifeStages() )
    val rand = new Random(variationIdx)     // Use variationIdx for seed
    // Shuffle
    val shuffled = rand.shuffle(allAnimals)

    val out = new ArrayBuffer[TaskModifier]
    for (i <- 0 until numAnimals) {
      for (animal <- shuffled(i)) {
        out.append(new TaskObject(animal.name, Some(animal), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true))
      }
    }

    out.toArray
  }

  // Make a task variation that includes (a) adding the living thing to the environment, (b) recording it's life stages in key/value pairs in the task modifiers
  def mkTaskVariation(livingThing:LivingThing, livingThingsToAdd:Array[EnvObject], location: String): Array[TaskModifier] = {

    // Get living thing life stages
    var lifestages = livingThing.lifecycle.get.stages.map(_.stageName)
    lifestages = lifestages.slice(0, lifestages.length - 1)               // Remove identifying the last life stage from the task, since it's usually always 'dead'
    val stageKeys = new ArrayBuffer[TaskModifier]
    for (i <- 0 until lifestages.length) {
      val lifestageName = lifestages(i)
      stageKeys.append(new TaskValueStr(key = "stage" + (i + 1), value = lifestageName))
      //println("stage" + i + "\t" + lifestageName)
    }

    // Create task modifier
    val out = new ArrayBuffer[TaskModifier]()

    val flowerPotNumbers = Random.shuffle( List(1, 2, 3, 4, 5, 6, 7, 8, 9) )

    // Add each plant
    var flowerPotIdx:Int = 0
    for (livingThing <- livingThingsToAdd) {
      // Plant must be in a (self watering) flower pot with soil to stay alive
      val flowerpot = new SelfWateringFlowerPot()
      flowerpot.addObject(new Soil())
      flowerpot.addObject(livingThing)

      flowerpot.name = "self watering flower pot " + flowerPotNumbers(flowerPotIdx)
      flowerPotIdx += 1

      out.append( new TaskObject(flowerpot.name, Some(flowerpot), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true) )
    }

    // Add a key describing which animal this task is for
    out.append( new TaskValueStr(key = "livingThingName", value = livingThing.propLife.get.lifeformType) )
    out.append( new TaskValueStr(key = "location", value = location) )

    // Add the life stage keys
    out.insertAll(out.length, stageKeys)

    return out.toArray
  }

}
