package scienceworld.tasks.specifictasks

import scienceworld.objects.agent.Agent
import scienceworld.objects.electricalcomponent.{Battery, ElectricBuzzer, ElectricMotor, LightBulb, Wire}
import scienceworld.objects.misc.{ForkMetal, ForkPlastic}
import scienceworld.objects.substance.{SodiumChloride, Water, Wood}
import scienceworld.objects.taskitems.{AnswerBox, UnknownSubstanceElectricalConductivity, UnknownSubstanceThermal}
import scienceworld.struct.EnvObject
import scienceworld.tasks.{Task, TaskMaker1, TaskModifier, TaskObject, TaskValueBool, TaskValueDouble, TaskValueStr}
import scienceworld.tasks.goals.{Goal, GoalSequence}
import scienceworld.tasks.goals.specificgoals.{GoalContainerByTemperature, GoalFind, GoalInRoomWithObject, GoalMoveToLocation, GoalMoveToNewLocation, GoalObjectInContainerByName, GoalObjectsInSingleContainer, GoalPastActionUseObjectOnObject, GoalSpecificObjectInDirectContainer}
import TaskUseInstrumentThermometer._
import scienceworld.actions.Action
import scienceworld.goldagent.PathFinder
import scienceworld.objects.containers.furniture.BeeHive
import scienceworld.objects.containers.{FlowerPot, Jug, SelfWateringFlowerPot, WoodCup}
import scienceworld.objects.devices.{Shovel, Sink, Thermometer}
import scienceworld.objects.livingthing.LivingThing
import scienceworld.objects.livingthing.plant.{PeaPlant, Plant, Soil}
import scienceworld.runtime.pythonapi.PythonInterface

import scala.collection.mutable.ArrayBuffer
import scala.util.Random
import scala.util.control.Breaks.{break, breakable}



class TaskUseInstrumentThermometer(val mode:String = MODE_USE_THERMOMETER) extends TaskParametric {
  val taskName = mode.replaceAll(" ", "-").replaceAll("[()]", "")

  val locations = Array("living room", "bedroom", "bathroom")

  // Variation 0: Always add the thermometer
  val instrument = new ArrayBuffer[ Array[TaskModifier] ]()
  val thermometer = new Thermometer()
  instrument.append( Array( new TaskObject(thermometer.name, Some(thermometer), roomToGenerateIn = "kitchen", Array.empty[String], generateNear = 0),
                            new TaskValueStr(key = "instrumentName", value = thermometer.name)
                          ))

  // Variation 1: Temperature point (above/below X degrees C)
  val temperaturePointPresets = Array(-50, 0, 50, 100, 200)
  val temperaturePoints = new ArrayBuffer[ Array[TaskModifier] ]()
  for (tempPoint <- temperaturePointPresets) {
    temperaturePoints.append( Array(new TaskValueDouble(key = "temperaturePoint", value = tempPoint)) )
  }

  // Variation 2+3: Substance to measure the temperature of, and temperature of substance
  val objectToTest = new ArrayBuffer[ Array[TaskModifier] ]()
  for (location <- locations) {
    for (tempPoint <- temperaturePointPresets) {

      // Substance 1: Salt
      val salt = new SodiumChloride()
      salt.propMaterial.get.temperatureC = TaskUseInstrumentThermometer.mkRandTemp(tempPoint)
      objectToTest.append(Array(
        new TaskObject(salt.name, Some(salt), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
        new TaskValueStr(key = "objectName", value = salt.name),
        new TaskValueStr(key = "location", value = location),
      ))

      // Substance 2: Plastic fork
      val metalfork = new ForkMetal()
      metalfork.propMaterial.get.temperatureC = TaskUseInstrumentThermometer.mkRandTemp(tempPoint)
      objectToTest.append(Array(
        new TaskObject(metalfork.name, Some(metalfork), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
        new TaskValueStr(key = "objectName", value = metalfork.name),
        new TaskValueStr(key = "location", value = location)
      ))

      // Substance 2: Plastic fork
      val wood = new Wood()
      wood.propMaterial.get.temperatureC = TaskUseInstrumentThermometer.mkRandTemp(tempPoint)
      objectToTest.append(Array(
        new TaskObject(wood.name, Some(wood), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
        new TaskValueStr(key = "objectName", value = wood.name),
        new TaskValueStr(key = "location", value = location)
      ))

      val wire = new Wire()
      wire.propMaterial.get.temperatureC = TaskUseInstrumentThermometer.mkRandTemp(tempPoint)
      objectToTest.append(Array(
        new TaskObject(wire.name, Some(wire), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
        new TaskValueStr(key = "objectName", value = wire.name),
        new TaskValueStr(key = "location", value = location)
      ))

      // Unknown (unnamed) substances)
      for (i <- 0 until 20) {
        val unknownSubstance = new UnknownSubstanceThermal("B")
        unknownSubstance.propMaterial.get.temperatureC = TaskUseInstrumentThermometer.mkRandTemp(tempPoint)
        objectToTest.append(Array(
          new TaskObject(unknownSubstance.name, Some(unknownSubstance), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
          new TaskValueStr(key = "objectName", value = unknownSubstance.name),
          new TaskValueStr(key = "location", value = location)
        ))
      }

    }
  }

  // Variation 4: Answer boxes
  val answerBoxes = new ArrayBuffer[ Array[TaskModifier] ]()
  val answerBoxColors = Array("red", "green", "blue", "orange", "yellow", "purple")
  for (location <- locations) {
    for (i <- 0 until answerBoxColors.length-1) {
      val colorAbove = answerBoxColors(i)
      val colorBelow = answerBoxColors(i+1)
      val boxAbove = new AnswerBox(colorAbove)
      val boxBelow = new AnswerBox(colorBelow)
      answerBoxes.append(Array(
        new TaskObject(boxAbove.name, Some(boxAbove), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
        new TaskObject(boxBelow.name, Some(boxBelow), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
        new TaskValueStr(key = "boxAbove", boxAbove.name),
        new TaskValueStr(key = "boxBelow", boxBelow.name),
        new TaskValueStr(key = "locationAnswerBox", location)
      ))
    }
  }

  // Sort so that substances remain separated in train/dev/test folds
  val objectToTestSorted = objectToTest.sortBy(getTaskValueStr(_, "objectName"))

  // Combinations
  var combinations = for {
    h <- instrument
    j <- objectToTestSorted
    i <- temperaturePoints
    k <- answerBoxes
  } yield List(h, j, i, k)

  // Subsample, since the number of combinations is large
  combinations = TaskUseInstrumentThermometer3.subsampleWithinTrainDevTest(combinations, subsampleProportion = 0.02)

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
    // Step 1: Extract modifier setup
    val objectName = this.getTaskValueStr(modifiers, "objectName")
    val objectLocation = this.getTaskValueStr(modifiers, "location")
    val tempPoint = this.getTaskValueDouble(modifiers, "temperaturePoint")
    val instrumentName = this.getTaskValueStr(modifiers, "instrumentName")
    val boxAbove = this.getTaskValueStr(modifiers, "boxAbove")
    val boxBelow = this.getTaskValueStr(modifiers, "boxBelow")
    val boxLocation = this.getTaskValueStr(modifiers, key = "locationAnswerBox")

    var subTask = ""
    val gSequence = new ArrayBuffer[Goal]
    val gSequenceUnordered = new ArrayBuffer[Goal]
    var description:String = "<empty>"
    if (mode == MODE_USE_THERMOMETER) {
      // Figure out the correct answer container based on the object's conductivity

      // Goal sequence
      gSequence.append(new GoalFind(objectName = instrumentName.get, failIfWrong = true, _defocusOnSuccess = true, description = "focus on instrument"))
      gSequence.append(new GoalFind(objectName = objectName.get, failIfWrong = true, _defocusOnSuccess = false, description = "focus on object"))    // Keep focus for next step
      gSequence.append(new GoalContainerByTemperature(tempThreshold = tempPoint.get, containerNameAbove = boxAbove.get, containerNameBelow = boxBelow.get, description = "move object to correct answer box"))

      // Unordered
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = instrumentName.get, _isOptional = true, description = "be in same location as " + instrumentName.get))
      gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName = "inventory", validObjectNames = Array("thermometer"), _isOptional = true, description = "have thermometer in inventory"))
      gSequenceUnordered.append(new GoalMoveToNewLocation(_isOptional = true, unlessInLocation = "", description = "move to a new location") )            // Move to any new location
      gSequenceUnordered.append(new GoalMoveToLocation(objectLocation.get, _isOptional = true, key = "move1", description = "move to the location asked by the task (object location)") )
      gSequenceUnordered.append(new GoalMoveToLocation(boxLocation.get, _isOptional = true, key = "move2", keysMustBeCompletedBefore = Array("move1"), description = "move to the location asked by the task (answer box location)") )
      gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName = "inventory", validObjectNames = Array(objectName.get), _isOptional = true, description = "have task object in inventory"))
      gSequenceUnordered.append(new GoalPastActionUseObjectOnObject(deviceName = instrumentName.get, patientObjectName = objectName.get, _isOptional = true, description = "use instrument on object"))
      gSequenceUnordered.append(new GoalPastActionUseObjectOnObject(deviceName = instrumentName.get, patientObjectName = objectName.get, _isOptional = true, keysMustBeCompletedBefore = Array("move2"), description = "use instrument on object (in answer box location)"))


      // Description
      description = "Your task is to measure the temperature of " + objectName.get + ", which is located around the " + objectLocation.get + ". "
      description += "First, focus on the thermometer. Next, focus on the " + objectName.get + ". "
      description += "If the " + objectName.get + " temperature is above " + tempPoint.get + " degrees celsius, place it in the " + boxAbove.get + ". "
      description += "If the " + objectName.get + " temperature is below " + tempPoint.get + " degrees celsius, place it in the " + boxBelow.get + ". "
      description += "The boxes are located around the " + boxLocation.get + ". "

    } else {
      throw new RuntimeException("ERROR: Unrecognized task mode: " + mode)
    }

    val taskLabel = taskName + "-variation" + combinationNum
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
    if (mode == MODE_USE_THERMOMETER) {
      return mkGoldActionSequenceThermometer(modifiers, runner)
    } else {
      throw new RuntimeException("ERROR: Unrecognized task mode: " + mode)
    }
  }

  /*
   * Gold action sequences
   */
  def mkGoldActionSequenceThermometer(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String]) = {
    val universe = runner.agentInterface.get.universe
    val agent = runner.agentInterface.get.agent

    // Task variables
    val objectName = this.getTaskValueStr(modifiers, "objectName").get
    val objectLocation = this.getTaskValueStr(modifiers, "location").get
    val tempPoint = this.getTaskValueDouble(modifiers, "temperaturePoint").get
    val instrumentName = this.getTaskValueStr(modifiers, "instrumentName").get
    val boxAbove = this.getTaskValueStr(modifiers, "boxAbove").get
    val boxBelow = this.getTaskValueStr(modifiers, "boxBelow").get
    val boxLocation = this.getTaskValueStr(modifiers, key = "locationAnswerBox").get

    val seedLocation = "greenhouse"


    // Stage 1: Get thermometer
    // Move from starting location to get instrument (thermometer)
    val (actions, actionStrs) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = "kitchen")
    runActionSequence(actionStrs, runner)

    // Look around
    runAction("look around", runner)

    // Take instrument (thermometer)
    val instruments = PathFinder.getAllAccessibleEnvObject(queryName = instrumentName, getCurrentAgentLocation(runner))
    if (instruments.length == 0) return (false, getActionHistory(runner))
    val instrument = instruments(0)
    //runAction("pick up " + PathFinder.getObjUniqueReferent(seedJar, getCurrentAgentLocation(runner)).get, runner)
    runAction("pick up " + instrument.name, runner)

    // Focus on instrument
    runAction("focus on " + instrument.name + " in inventory", runner)


    // Stage 2: Get task object
    // Go to task location
    val (actions1, actionStrs1) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = objectLocation)
    runActionSequence(actionStrs1, runner)

    // Look around
    runAction("look around", runner)

    // Pick up the task object
    val objects = PathFinder.getAllAccessibleEnvObject(queryName = objectName, getCurrentAgentLocation(runner))
    if (objects.length == 0) return (false, getActionHistory(runner))
    val taskObject = objects(0)
    //runAction("pick up " + PathFinder.getObjUniqueReferent(seedJar, getCurrentAgentLocation(runner)).get, runner)
    runAction("pick up " + taskObject.name, runner)

    // Focus on task object
    runAction("focus on " + taskObject.name + " in inventory", runner)


    // Stage 3: Move to answer box location
    // Go to task location
    val (actions2, actionStrs2) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = boxLocation)
    runActionSequence(actionStrs2, runner)

    // Look around
    runAction("look around", runner)


    // Stage 4: Measure temperature and select answer box
    runAction("use " + instrument.name + " in inventory on " + taskObject.name + " in inventory", runner)
    val objTempC = taskObject.propMaterial.get.temperatureC

    if (objTempC > tempPoint) {
      // Above threshold
      runAction("move " + taskObject.name + " in inventory to " + boxAbove, runner)
    } else {
      // Below threshold
      runAction("move " + taskObject.name + " in inventory to " + boxBelow, runner)
    }


    // Wait one moment
    runAction("wait1", runner)

    // Return
    return (true, getActionHistory(runner))
  }

}


object TaskUseInstrumentThermometer {
  val MODE_USE_THERMOMETER            = "use thermometer"

  def registerTasks(taskMaker:TaskMaker1): Unit = {
    taskMaker.addTask( new TaskUseInstrumentThermometer(mode = MODE_USE_THERMOMETER) )
  }

  // Make a random temperature that's 50-150C above/below 'tempPoint'
  def mkRandTemp(tempPoint:Double):Double = {
    var tempDelta = Random.nextInt(100) + 50                      // Randomly generate a number 0-100, then add 50 to it (so 50-150 range)
    if (Random.nextBoolean() == true) tempDelta = -tempDelta      // Randomly change the sign (+/- 50-150)
    val randTemp = tempPoint + tempDelta                          // Create a temperature that's randomly +/- 50-150 above/below the temperature set point

    return math.floor( randTemp )
  }

}
