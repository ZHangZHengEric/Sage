package scienceworld.tasks.specifictasks

import scienceworld.objects.agent.Agent
import scienceworld.objects.devices.Thermometer
import scienceworld.objects.electricalcomponent.Wire
import scienceworld.objects.misc.ForkMetal
import scienceworld.objects.substance.{Gallium, Lead, Mercury, SodiumChloride, Tin, Water, Wood}
import scienceworld.objects.taskitems.{AnswerBox, UnknownSubstanceThermal}
import scienceworld.struct.EnvObject
import scienceworld.tasks.{Task, TaskMaker1, TaskModifier, TaskObject, TaskValueDouble, TaskValueStr}
import scienceworld.tasks.goals.{Goal, GoalSequence}
import scienceworld.tasks.goals.specificgoals.{GoalActivateDeviceWithName, GoalContainerByTemperature, GoalFind, GoalFindAnswerBox, GoalInRoomWithObject, GoalMoveToLocation, GoalMoveToNewLocation, GoalObjectInContainer, GoalObjectsInSingleContainer, GoalPastActionUseObjectOnObject, GoalSpecificObjectInDirectContainer, GoalTemperatureIncrease, GoalTemperatureOnFire}
import TaskUseInstrumentThermometer2._
import scienceworld.actions.Action
import scienceworld.environments.ContainerMaker
import scienceworld.goldagent.PathFinder
import scienceworld.objects.containers.MetalPot
import scienceworld.objects.substance.food.{Chocolate, OrangeJuice}
import scienceworld.runtime.pythonapi.PythonInterface

import scala.collection.mutable.ArrayBuffer
import scala.util.Random
import scala.util.control.Breaks._


class TaskUseInstrumentThermometer2(val mode:String = MODE_MEASURE_MELTING_KNOWN) extends TaskParametric {
  val taskName = mode.replaceAll(" ", "-").replaceAll("[()]", "")

  val locations = Array("kitchen")

  // Variation 0: Always add the thermometer
  val instrument = new ArrayBuffer[ Array[TaskModifier] ]()
  val thermometer = new Thermometer()
  instrument.append( Array( new TaskObject(thermometer.name, Some(thermometer), roomToGenerateIn = "kitchen", Array.empty[String], generateNear = 0),
    new TaskValueStr(key = "instrumentName", value = thermometer.name)
  ))

  // Variation 1: Temperature point (above/below X degrees C)
  //val temperaturePointPresets = Array(-50, 10, 50, 150, 250)
  val temperaturePointPresets = Array(-10, 10, 50, 150, 200)
  val temperaturePoints = new ArrayBuffer[ Array[TaskModifier] ]()
  for (tempPoint <- temperaturePointPresets) {
    temperaturePoints.append( Array(new TaskValueDouble(key = "temperaturePoint", value = tempPoint)) )
  }

  // Variation 2+3: Substance to measure the temperature of, and temperature of substance
  val objectToTest = new ArrayBuffer[ Array[TaskModifier] ]()
  for (location <- locations) {
    for (tempPoint <- temperaturePointPresets) {

      // Substance 1: Water
      val water = new Water()
      //water.propMaterial.get.temperatureC = TaskUseInstrumentThermometer.mkRandTemp(tempPoint)    // no need to generate in environment
      objectToTest.append(Array(
        new TaskObject(water.name, None, roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
        new TaskValueStr(key = "objectName", value = water.name),
        new TaskValueStr(key = "location", value = location),
        new TaskValueDouble(key = "meltingPoint", value = water.propMaterial.get.meltingPoint)
      ))

      /*
       *   substancePossibilities.append( Array(new TaskObject("orange juice", Some(ContainerMaker.mkRandomLiquidCup(new OrangeJuice)), "kitchen", Array("fridge"), 0) ))
  substancePossibilities.append( Array(new TaskObject("apple juice", Some(ContainerMaker.mkRandomLiquidCup(new AppleJuice)), "kitchen", Array("fridge"), 0) ))
  substancePossibilities.append( )
  substancePossibilities.append( Array(new TaskObject("marshmallow", Some(new Marshmallow), roomToGenerateIn = "kitchen", Array("cupboard", "table", "desk"), generateNear = 0) ))
  substancePossibilities.append( Array(new TaskObject("ice cream", Some(ContainerMaker.mkRandomLiquidCup(new IceCream)), roomToGenerateIn = "kitchen", Array("freezer"), generateNear = 0) ))

       */
      // Substance 2: Orange Juice
      val orangejuice = new OrangeJuice()
      objectToTest.append(Array(
        new TaskObject("orange juice", Some(ContainerMaker.mkRandomLiquidCup(new OrangeJuice)), "kitchen", Array("fridge"), 0),
        new TaskValueStr(key = "objectName", value = orangejuice.name),
        new TaskValueStr(key = "location", value = location),
        new TaskValueDouble(key = "meltingPoint", value = orangejuice.propMaterial.get.meltingPoint)
      ))

      // Substance 3: Chocolate
      val chocolate = new Chocolate()
      objectToTest.append(Array(
        new TaskObject("chocolate", Some(chocolate), "kitchen", Array("fridge"), 0),
        new TaskValueStr(key = "objectName", value = chocolate.name),
        new TaskValueStr(key = "location", value = location),
        new TaskValueDouble(key = "meltingPoint", value = chocolate.propMaterial.get.meltingPoint)
      ))

      // Substance 4
      val mercury = new Mercury()
      objectToTest.append(Array(
        new TaskObject(mercury.name, Some(ContainerMaker.mkRandomLiquidCup(mercury)), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
        new TaskValueStr(key = "objectName", value = mercury.name),
        new TaskValueStr(key = "location", value = location),
        new TaskValueDouble(key = "meltingPoint", value = mercury.propMaterial.get.meltingPoint)
      ))

      // Substance 5
      val gallium = new Gallium()
      objectToTest.append(Array(
        new TaskObject(gallium.name, Some(ContainerMaker.mkRandomLiquidCup(gallium)), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
        new TaskValueStr(key = "objectName", value = gallium.name),
        new TaskValueStr(key = "location", value = location),
        new TaskValueDouble(key = "meltingPoint", value = gallium.propMaterial.get.meltingPoint)
      ))

      // Substance 6
      val tin = new Tin()
      objectToTest.append(Array(
        new TaskObject(tin.name, Some(ContainerMaker.mkRandomLiquidCup(tin)), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
        new TaskValueStr(key = "objectName", value = tin.name),
        new TaskValueStr(key = "location", value = location),
        new TaskValueDouble(key = "meltingPoint", value = tin.propMaterial.get.meltingPoint)
      ))

      // Substance 7
      val lead = new Lead()
      objectToTest.append(Array(
        new TaskObject(lead.name, Some(ContainerMaker.mkRandomLiquidCup(lead)), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
        new TaskValueStr(key = "objectName", value = lead.name),
        new TaskValueStr(key = "location", value = location),
        new TaskValueDouble(key = "meltingPoint", value = lead.propMaterial.get.meltingPoint)
      ))

      /*
      // Unknown (unnamed) substances)
      for (i <- 0 until 20) {
        val unknownSubstance = new UnknownSubstanceThermal()
        unknownSubstance.propMaterial.get.temperatureC = TaskUseInstrumentThermometer.mkRandTemp(tempPoint)
        objectToTest.append(Array(
          new TaskObject(unknownSubstance.name, Some(unknownSubstance), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
          new TaskValueStr(key = "objectName", value = unknownSubstance.name),
          new TaskValueStr(key = "location", value = location)
        ))
      }
       */

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
  combinations = TaskUseInstrumentThermometer3.subsampleWithinTrainDevTest(combinations, subsampleProportion = 0.50)

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
    val meltingPoint = this.getTaskValueDouble(modifiers, "meltingPoint")
    val instrumentName = this.getTaskValueStr(modifiers, "instrumentName")
    val boxAbove = this.getTaskValueStr(modifiers, "boxAbove")
    val boxBelow = this.getTaskValueStr(modifiers, "boxBelow")
    val boxLocation = this.getTaskValueStr(modifiers, key = "locationAnswerBox")

    var subTask = ""
    val gSequence = new ArrayBuffer[Goal]
    val gSequenceUnordered = new ArrayBuffer[Goal]
    var description:String = "<empty>"
    if (mode == MODE_MEASURE_MELTING_KNOWN) {
      // Figure out the correct answer container based on the object's conductivity

      // Goal sequence
      gSequence.append(new GoalFind(objectName = instrumentName.get, failIfWrong = true, _defocusOnSuccess = true, description = "focus on thermometer"))
      gSequence.append(new GoalFind(objectName = objectName.get, failIfWrong = true, _defocusOnSuccess = false, key = "focusObject", description = "focus on substance"))   // Keep focus
      if (meltingPoint.get >= tempPoint.get) {
        println ("FOCUS 1")
        gSequence.append(new GoalFindAnswerBox(objectName = boxAbove.get, failIfWrong = true, description = "focus on correct answer box"))
      } else {
        println ("FOCUS 2")
        gSequence.append(new GoalFindAnswerBox(objectName = boxBelow.get, failIfWrong = true, description = "focus on correct answer box"))
      }

      // Thermometer
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = "thermometer", _isOptional = true, description = "be in same location as thermometer"))
      gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName = "inventory", validObjectNames = Array("thermometer"), _isOptional = true, description = "have thermometer in inventory"))

      // Moving to helpful locations
      gSequenceUnordered.append(new GoalMoveToNewLocation(_isOptional = true, unlessInLocation = "", description = "move to a new location") )            // Move to any new location
      gSequenceUnordered.append(new GoalMoveToLocation(objectLocation.get, _isOptional = true, key = "move1", description = "move to the location asked by the task (substance location)") )
      gSequenceUnordered.append(new GoalMoveToLocation(boxLocation.get, _isOptional = true, key = "move1", description = "move to the location asked by the task (answer box location)") )
      gSequenceUnordered.append(new GoalMoveToLocation("kitchen", _isOptional = true, key = "move2a", keysMustBeCompletedBefore = Array("move1"), description = "move to a location with a heating device (kitchen)") )
      gSequenceUnordered.append(new GoalMoveToLocation("outside", _isOptional = true, key = "move2b", keysMustBeCompletedBefore = Array("move1"), description = "move to a location with a heating device (outside)") )
      gSequenceUnordered.append(new GoalMoveToLocation("foundry", _isOptional = true, key = "move2c", keysMustBeCompletedBefore = Array("move1"), description = "move to a location with a heating device (foundry)") )

      // Pick up substance (potentially useful)
      gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName = "inventory", validObjectNames = Array(objectName.get), _isOptional = true, description = "have task object in inventory"))

      // Use thermometer on substance
      gSequenceUnordered.append(new GoalPastActionUseObjectOnObject(deviceName = instrumentName.get, patientObjectName = objectName.get, _isOptional = true, description = "use thermometer on substance"))
      gSequenceUnordered.append(new GoalPastActionUseObjectOnObject(deviceName = instrumentName.get, patientObjectName = objectName.get, _isOptional = true, keysMustBeCompletedBefore = Array("heatObject"), description = "use thermometer on substance (after it has been heated)"))

      // Have the substance alone in a single container
      gSequenceUnordered.append(new GoalObjectsInSingleContainer(objectNames = Array(objectName.get), _isOptional = true, description = "have substance alone in a single container"))

      // Activate a heating device
      gSequenceUnordered.append(new GoalActivateDeviceWithName(deviceName = "stove", _isOptional = true, description = "activate heater (stove)"))
      gSequenceUnordered.append(new GoalActivateDeviceWithName(deviceName = "blast furnace", _isOptional = true, description = "activate heater (blast furnace)"))
      gSequenceUnordered.append(new GoalActivateDeviceWithName(deviceName = "oven", _isOptional = true, description = "activate heater (oven)"))
      gSequenceUnordered.append(new GoalActivateDeviceWithName(deviceName = "hot plate", _isOptional = true, description = "activate heater (hot plate)"))
      // Or, build a fire in the fire pit
      gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName = "inventory", validObjectNames = Array("lighter"), _isOptional = true, description = "have lighter in inventory"))
      gSequenceUnordered.append(new GoalSpecificObjectInDirectContainer(containerName = "fire pit", validObjectNames = Array("wood"), _isOptional = true, description = "move wood into fire pit", key = "wood1"))
      gSequenceUnordered.append(new GoalTemperatureOnFire(objectName = "wood", _isOptional = true, description = "ignite wood", key = "ignite", keysMustBeCompletedBefore = Array("wood1")) )

      // Put the substance on a heating device
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "stove", _isOptional = true, keysMustBeCompletedBefore = Array("focusObject"), description = "have substance on heater (stove)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "blast furnace", _isOptional = true, keysMustBeCompletedBefore = Array("focusObject"), description = "have substance on heater (blast furnace)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "oven", _isOptional = true, keysMustBeCompletedBefore = Array("focusObject"), description = "have substance on heater (oven)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "hot plate", _isOptional = true, keysMustBeCompletedBefore = Array("focusObject"), description = "have substance on heater (hot plate)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "fire pit", _isOptional = true, keysMustBeCompletedBefore = Array("focusObject"), description = "have substance on heater (fire pit)"))

      // Heat object (when the substance is in focus)
      gSequenceUnordered.append(new GoalTemperatureIncrease(minTempIncreaseC = 20.0, _isOptional = true, key = "heatObject", keysMustBeCompletedBefore = Array("focusObject"), description = "heat substance by at least 20C"))



      // Description
      description = "Your task is to measure the melting point of " + objectName.get + ", which is located around the " + objectLocation.get + ". "
      description += "First, focus on the thermometer. Next, focus on the " + objectName.get + ". "
      description += "If the melting point of " + objectName.get + " is above " + tempPoint.get + " degrees celsius, focus on the " + boxAbove.get + ". "
      description += "If the melting point of " + objectName.get + " is below " + tempPoint.get + " degrees celsius, focus on the " + boxBelow.get + ". "
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
    if (mode == MODE_MEASURE_MELTING_KNOWN) {
      return mkGoldActionSequenceThermometer(modifiers, runner)
    } else {
      throw new RuntimeException("ERROR: Unrecognized task mode: " + mode)
    }
  }


  def mkGoldActionSequenceThermometer(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String]) = {
    val universe = runner.agentInterface.get.universe
    val agent = runner.agentInterface.get.agent

    // Task variables
    val objectName = this.getTaskValueStr(modifiers, "objectName").get
    val objectLocation = this.getTaskValueStr(modifiers, "location").get
    val tempPoint = this.getTaskValueDouble(modifiers, "temperaturePoint").get
    val meltingPoint = this.getTaskValueDouble(modifiers, "meltingPoint").get
    val instrumentName = this.getTaskValueStr(modifiers, "instrumentName").get
    val boxAbove = this.getTaskValueStr(modifiers, "boxAbove").get
    val boxBelow = this.getTaskValueStr(modifiers, "boxBelow").get
    val boxLocation = this.getTaskValueStr(modifiers, key = "locationAnswerBox").get

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

    // Check to make sure the task object is available in an accessible container
    var taskObject:EnvObject = null
    if (objectName == "water") {
      // Attempt to find water
      val (success, waterContainer, waterRef) = PathFinder.getWaterInContainer(runner)

      if (!success) {
        //## runAction("NOTE: WAS NOT ABLE TO FIND WATER", runner)
      }

      taskObject = waterRef.get

    } else {
      var successOpeningContainers: Boolean = true
      var substances: Array[EnvObject] = Array.empty[EnvObject]
      breakable {
        for (i <- 0 to 20) {
          println("*** FIND SUBSTANCE ATTEMPT " + i)
          substances = PathFinder.getAllAccessibleEnvObject(objectName, getCurrentAgentLocation(runner))
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
      val objects = PathFinder.getAllAccessibleEnvObject(queryName = objectName, getCurrentAgentLocation(runner))
      if (objects.length == 0) {
        //## runAction("NOTE: WAS NOT ABLE TO FIND SUBSTANCE (" + objectName + ")", runner)
        return (false, getActionHistory(runner))
      }

      taskObject = objects(0)
    }

    // Two possibilities: Substance is a liquid (so needs to be cooled), or substance is a solid (and needs to be heated).
    var objTempC:Double = 0.0f    // Ultimate approximate melting point from either method

    if (taskObject.propMaterial.get.stateOfMatter == "solid") {
      // Substance is a solid -- do heating procedure to determine melting point

      // Focus on task object
      runAction("focus on " + PathFinder.getObjUniqueReferent(taskObject, getCurrentAgentLocation(runner)).get, runner)

      runAction("open cupboard", runner)

      val container = getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[MetalPot]().toList(0)

      runAction("move " + PathFinder.getObjUniqueReferent(taskObject, getCurrentAgentLocation(runner)).get + " to " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)


      if (meltingPoint < 200.0f) {
        // Since these substances are known, we can guess to use the stove or furnace on them.

        // Use stove
        val heatingDeviceName:String = "stove"
        runAction("move " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get + " to " + heatingDeviceName, runner)

        runAction("activate " + heatingDeviceName, runner)

      } else {
        // Use blast furnace
        runAction("pick up " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)

        // Go to foundry
        val (actions2, actionStrs2) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = "foundry")
        runActionSequence(actionStrs2, runner)

        val heatingDeviceName:String = "blast furnace"
        runAction("open " + heatingDeviceName, runner)
        runAction("move " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get + " to " + heatingDeviceName, runner)

        runAction("activate " + heatingDeviceName, runner)
      }

      val MAX_ITER = 40
      breakable {
        for (i <- 0 until MAX_ITER) {
          // Check to see object's state of matter
          runAction("examine " + PathFinder.getObjUniqueReferent(taskObject, getCurrentAgentLocation(runner)).get, runner)
          val objSOM = taskObject.propMaterial.get.stateOfMatter

          // Measure object temperature
          objTempC = taskObject.propMaterial.get.temperatureC
          runAction("use " + instrument.name + " in inventory on " + PathFinder.getObjUniqueReferent(taskObject, getCurrentAgentLocation(runner)).get, runner)


          // Break when the object is no longer a liquid
          if (objSOM != "solid") break()
        }
      }


    } else {
      // Substance is a liquid -- do cooling procedure to determine melting (freezing) point
      val substanceContainer = taskObject.getContainer().get

      //runAction("pick up " + PathFinder.getObjUniqueReferent(seedJar, getCurrentAgentLocation(runner)).get, runner)
      runAction("pick up " + PathFinder.getObjUniqueReferent(substanceContainer, getCurrentAgentLocation(runner)).get, runner)

      // Focus on task object
      runAction("focus on " + PathFinder.getObjUniqueReferent(taskObject, getCurrentAgentLocation(runner)).get, runner)

      // Move task object to freezer
      val coolingDeviceName:String = "freezer"
      runAction("open " + coolingDeviceName, runner)

      runAction("move " + PathFinder.getObjUniqueReferent(substanceContainer, getCurrentAgentLocation(runner)).get + " to " + coolingDeviceName, runner)

      val MAX_ITER = 30
      breakable {
        for (i <- 0 until MAX_ITER) {
          // Check to see object's state of matter
          runAction("examine " + PathFinder.getObjUniqueReferent(taskObject, getCurrentAgentLocation(runner)).get, runner)
          val objSOM = taskObject.propMaterial.get.stateOfMatter

          // Measure object temperature
          objTempC = taskObject.propMaterial.get.temperatureC
          runAction("use " + instrument.name + " in inventory on " + PathFinder.getObjUniqueReferent(taskObject, getCurrentAgentLocation(runner)).get, runner)

          // Break when the object is no longer a liquid
          if (objSOM != "liquid") break()
        }
      }

    }

    // Go to answer box location
    val (actions2, actionStrs2) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = boxLocation)
    runActionSequence(actionStrs2, runner)


    // Choose correct box based on temperature
    if (objTempC > tempPoint) {
      //## runAction("NOTE: Object Temperature ( " + objTempC + ") is ABOVE temperature point (" + tempPoint + ")", runner)
      // Above threshold
      runAction("focus on " + boxAbove, runner)
    } else {
      //## runAction("NOTE: Object Temperature ( " + objTempC + ") is BELOW temperature point (" + tempPoint + ")", runner)
      // Below threshold
      runAction("focus on " + boxBelow, runner)
    }


    // Wait one moment
    runAction("wait1", runner)

    // Return
    return (true, getActionHistory(runner))
  }

}


object TaskUseInstrumentThermometer2 {
  val MODE_MEASURE_MELTING_KNOWN            = "measure melting point (known substance)"

  def registerTasks(taskMaker:TaskMaker1): Unit = {
    taskMaker.addTask( new TaskUseInstrumentThermometer2(mode = MODE_MEASURE_MELTING_KNOWN) )
  }

  // Make a random temperature that's 50-150C above/below 'tempPoint'
  def mkRandTemp(tempPoint:Double):Double = {
    var tempDelta = Random.nextInt(100) + 50                      // Randomly generate a number 0-100, then add 50 to it (so 50-150 range)
    if (Random.nextBoolean() == true) tempDelta = -tempDelta      // Randomly change the sign (+/- 50-150)
    val randTemp = tempPoint + tempDelta                          // Create a temperature that's randomly +/- 50-150 above/below the temperature set point

    return math.floor( randTemp )
  }

}
