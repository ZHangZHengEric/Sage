package scienceworld.tasks.specifictasks

import scienceworld.actions.Action
import scienceworld.environments.ContainerMaker
import scienceworld.goldagent.PathFinder
import scienceworld.objects.agent.Agent
import scienceworld.objects.containers.MetalPot
import scienceworld.objects.devices.Stove
import scienceworld.objects.substance.food.{AppleJuice, Chocolate, IceCream, Marshmallow, OrangeJuice}
import scienceworld.objects.substance.{Caesium, Gallium, Ice, Lead, Mercury, Rubber, Soap, Tin}
import scienceworld.objects.taskitems.UnknownSubstanceThermal
import scienceworld.runtime.pythonapi.PythonInterface
import scienceworld.struct.EnvObject
import scienceworld.tasks.{Task, TaskDisable, TaskMaker1, TaskModifier, TaskObject, TaskValueStr}
import scienceworld.tasks.goals.{Goal, GoalSequence}
import scienceworld.tasks.goals.specificgoals.{GoalActivateDeviceWithName, GoalChangeStateOfMatter, GoalFind, GoalInRoomWithObject, GoalIsDifferentStateOfMatter, GoalIsNotStateOfMatter, GoalIsStateOfMatter, GoalMoveToLocation, GoalMoveToNewLocation, GoalObjectInContainer, GoalObjectInContainerByName, GoalObjectsInSingleContainer, GoalSpecificObjectInDirectContainer, GoalTemperatureDecrease, GoalTemperatureIncrease, GoalTemperatureOnFire}
import scienceworld.tasks.specifictasks.TaskChangeOfState.{MODE_BOIL, MODE_CHANGESTATE, MODE_FREEZE, MODE_MELT}

import scala.collection.mutable.ArrayBuffer
import scala.util.Random
import scala.util.control.Breaks.{break, breakable}


class TaskChangeOfState(val mode:String = MODE_CHANGESTATE) extends TaskParametric {
  val taskName = mode.replaceAll(" ", "-").replaceAll("[()]", "")

  val substancePossibilities = new ArrayBuffer[ Array[TaskModifier] ]()
  // Example of water (found in the environment)
  substancePossibilities.append( Array(new TaskObject("water", None, "", Array.empty[String], 0),
      new TaskValueStr(key = "objectName", value = "water") ))

  // Water, but disable the common source (the sink in the kitchen)
  substancePossibilities.append( Array(new TaskObject("water", None, "", Array.empty[String], 0),
      new TaskDisable(name="sink", Array("kitchen")),
      new TaskValueStr(key = "objectName", value = "water") ))

  // Example of ice (needs to be generated)
  substancePossibilities.append( Array(new TaskObject("ice", Some(new Ice), "kitchen", Array("freezer"), 0),
    new TaskValueStr(key = "objectName", value = "ice")))
  // Example of something needing to be generated
  substancePossibilities.append( Array(new TaskObject("orange juice", Some(ContainerMaker.mkRandomLiquidCup(new OrangeJuice)), "kitchen", Array("fridge"), 0),
    new TaskValueStr(key = "objectName", value = "orange juice")))
  substancePossibilities.append( Array(new TaskObject("apple juice", Some(ContainerMaker.mkRandomLiquidCup(new AppleJuice)), "kitchen", Array("fridge"), 0),
    new TaskValueStr(key = "objectName", value = "apple juice")))
  substancePossibilities.append( Array(new TaskObject("chocolate", Some(new Chocolate), "kitchen", Array("fridge"), 0),
    new TaskValueStr(key = "objectName", value = "chocolate")))
  substancePossibilities.append( Array(new TaskObject("marshmallow", Some(new Marshmallow), roomToGenerateIn = "kitchen", Array("cupboard", "table", "desk"), generateNear = 0),
    new TaskValueStr(key = "objectName", value = "marshmallow")))
  substancePossibilities.append( Array(new TaskObject("ice cream", Some(ContainerMaker.mkRandomLiquidCup(new IceCream)), roomToGenerateIn = "kitchen", Array("freezer"), generateNear = 0),
    new TaskValueStr(key = "objectName", value = "ice cream")))

  substancePossibilities.append( Array(new TaskObject("soap", Some(new Soap), roomToGenerateIn = "kitchen", Array("cupboard", "table", "desk"), generateNear = 0),
    new TaskValueStr(key = "objectName", value = "soap")))
  substancePossibilities.append( Array(new TaskObject("rubber", Some(new Rubber), roomToGenerateIn = "workshop", Array("table", "desk"), generateNear = 0),
    new TaskValueStr(key = "objectName", value = "rubber")))

  substancePossibilities.append( Array(new TaskObject("lead", Some(TaskChangeOfState.mkSubstanceInContainer(new Lead())), "workshop", Array("table", "desk"), forceAdd = true),
    new TaskValueStr(key = "objectName", value = "lead")))
  substancePossibilities.append( Array(new TaskObject("tin", Some(TaskChangeOfState.mkSubstanceInContainer(new Tin())), "workshop", Array("table", "desk"), forceAdd = true),
    new TaskValueStr(key = "objectName", value = "tin")))
  substancePossibilities.append( Array(new TaskObject("mercury", Some(TaskChangeOfState.mkSubstanceInContainer(new Mercury())), "workshop", Array("table", "desk"), forceAdd = true),
    new TaskValueStr(key = "objectName", value = "mercury")))
  substancePossibilities.append( Array(new TaskObject("gallium", Some(TaskChangeOfState.mkSubstanceInContainer(new Gallium())), "workshop", Array("table", "desk"), forceAdd = true),
    new TaskValueStr(key = "objectName", value = "gallium")))
  substancePossibilities.append( Array(new TaskObject("caesium", Some(TaskChangeOfState.mkSubstanceInContainer(new Caesium())), "workshop", Array("table", "desk"), forceAdd = true),
    new TaskValueStr(key = "objectName", value = "caesium")))



  val toolPossibilities = new ArrayBuffer[ Array[TaskModifier] ]()
  // Case 1: Normal (stove in kitchen)
  toolPossibilities.append( Array(new TaskObject("stove", Some(new Stove), roomToGenerateIn = "kitchen", Array(""), generateNear = 0) ))
  // Case 2: Disable stove in kitchen (also should add an alternate)
  toolPossibilities.append( Array(new TaskDisable("stove", Array("kitchen") ) ) )


  // Combinations
  val combinations = for {
    i <- substancePossibilities
    j <- toolPossibilities
  } yield List(i, j)

  println("Number of combinations: " + combinations.length)

  def numCombinations():Int = this.combinations.size

  def getCombination(idx:Int):Array[TaskModifier] = {
    val out = new ArrayBuffer[TaskModifier]
    for (elem <- combinations(idx)) {
      out.insertAll(out.length, elem)
    }

    println ("* getCombination: out.length: " + out.length)
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
    Random.setSeed(combinationNum)
    return this.setupCombination( this.getCombination(combinationNum), universe, agent )
  }


  // Setup a set of subgoals for this task modifier combination.
  private def setupGoals(modifiers:Array[TaskModifier], combinationNum:Int): Task = {
    // Step 1: Find substance name
    // NOTE: The first modifier here will be the substance to change the state of.
    val substanceModifier = modifiers(0)
    var substanceName = "<unknown>"
    substanceModifier match {
      case m:TaskObject => {
        substanceName = m.name
      }
      case _ => {
        throw new RuntimeException("ERROR: Unknown task modifier found, where substance modifier was expected." + substanceModifier.toString)
      }
    }

    var subTask = ""
    val gSequence = new ArrayBuffer[Goal]
    val gSequenceUnordered = new ArrayBuffer[Goal]
    if (mode == MODE_CHANGESTATE) {
      subTask = "change the state of matter of"
      gSequence.append( new GoalFind(objectName = substanceName, description = "focus on substance") )
      gSequence.append( new GoalIsStateOfMatter() )             // Be in any state
      gSequence.append( new GoalIsDifferentStateOfMatter() )    // Be in any state but the first state

      // Unordered
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = substanceName, _isOptional = true, description = "be in same location as " + substanceName))
      gSequenceUnordered.append(new GoalObjectsInSingleContainer(objectNames = Array(substanceName), _isOptional = true, description = "have substance alone in a single container"))

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
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "stove", _isOptional = true, description = "have object on heater (stove)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "blast furnace", _isOptional = true, description = "have object on heater (blast furnace)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "oven", _isOptional = true, description = "have object on heater (oven)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "hot plate", _isOptional = true, description = "have object on heater (hot plate)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "fire pit", _isOptional = true, description = "have object on heater (fire pit)"))

      // Or, put substance in a cooling device
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "fridge", _isOptional = true, description = "have object in cooler (fridge)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "freezer", _isOptional = true, description = "have object in cooler (freezer)"))

      // Heat object
      gSequenceUnordered.append(new GoalTemperatureIncrease(minTempIncreaseC = 10.0, _isOptional = true, description = "heat object by at least 10C"))
      // Or, cool object
      gSequenceUnordered.append(new GoalTemperatureDecrease(minTempDecreaseC = 10.0, _isOptional = true, description = "cool object by at least 10C"))



    } else if (mode == MODE_MELT) {
      subTask = "melt"
      gSequence.append( new GoalFind(objectName = substanceName, description = "focus on substance") )
      gSequence.append( new GoalChangeStateOfMatter("solid", description = "substance is in a solid state") )
      gSequence.append( new GoalChangeStateOfMatter("liquid", description = "substance is in a liquid state") )

      // Unordered
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = substanceName, _isOptional = true, description = "be in same location as " + substanceName))
      gSequenceUnordered.append(new GoalObjectsInSingleContainer(objectNames = Array(substanceName), _isOptional = true, description = "have substance alone in a single container"))

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
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "stove", _isOptional = true, description = "have object on heater (stove)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "blast furnace", _isOptional = true, description = "have object on heater (blast furnace)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "oven", _isOptional = true, description = "have object on heater (oven)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "hot plate", _isOptional = true, description = "have object on heater (hot plate)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "fire pit", _isOptional = true, description = "have object on heater (fire pit)"))

      // Heat object
      gSequenceUnordered.append(new GoalTemperatureIncrease(minTempIncreaseC = 20.0, _isOptional = true, description = "heat object by at least 20C"))


    } else if (mode == MODE_BOIL) {
      subTask = "boil"
      gSequence.append( new GoalFind(objectName = substanceName, description = "focus on substance") )
      gSequence.append( new GoalChangeStateOfMatter("liquid", description = "substance is in a liquid state") )
      gSequence.append( new GoalChangeStateOfMatter("gas", combustionAllowed = true, description = "substance is in a gaseous state (or combusting)") )

      // Unordered
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = substanceName, _isOptional = true, description = "be in same location as " + substanceName))
      gSequenceUnordered.append(new GoalObjectsInSingleContainer(objectNames = Array(substanceName), _isOptional = true, description = "have substance alone in a single container"))

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
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "stove", _isOptional = true, description = "have object on heater (stove)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "blast furnace", _isOptional = true, description = "have object on heater (blast furnace)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "oven", _isOptional = true, description = "have object on heater (oven)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "hot plate", _isOptional = true, description = "have object on heater (hot plate)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "fire pit", _isOptional = true, description = "have object on heater (fire pit)"))

      // Heat object
      gSequenceUnordered.append(new GoalTemperatureIncrease(minTempIncreaseC = 20.0, _isOptional = true, description = "heat object by at least 20C"))

    } else if (mode == MODE_FREEZE) {
      subTask = "freeze"
      gSequence.append( new GoalFind(objectName = substanceName, description = "focus on substance") )
      gSequence.append( new GoalChangeStateOfMatter("liquid", description = "substance is in a liquid state") )
      gSequence.append( new GoalChangeStateOfMatter("solid", description = "substance is in a solid state") )

      // Unordered
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = substanceName, _isOptional = true, description = "be in same location as " + substanceName))
      gSequenceUnordered.append(new GoalObjectsInSingleContainer(objectNames = Array(substanceName), _isOptional = true, description = "have substance alone in a single container"))

      // Put substance in a cooling device
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "fridge", _isOptional = true, description = "have object in cooler (fridge)"))
      gSequenceUnordered.append(new GoalObjectInContainer(containerName = "freezer", _isOptional = true, description = "have object in cooler (freezer)"))

      // Cool object
      gSequenceUnordered.append(new GoalTemperatureDecrease(minTempDecreaseC = 5.0, _isOptional = true, description = "cool object by at least 5C"))

    } else {
      throw new RuntimeException("ERROR: Unrecognized task mode: " + mode)
    }

    val taskLabel = taskName + "-variation" + combinationNum
    var description = "Your task is to " + subTask + " " + substanceName + ". "
    if (mode == MODE_BOIL) description += "For compounds without a boiling point, combusting the substance is also acceptable. "
    description += "First, focus on the substance. Then, take actions that will cause it to change its state of matter. "
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
    if (mode == MODE_MELT) {
      return mkGoldActionSequenceChangeState(modifiers, runner)
    } else if (mode == MODE_BOIL) {
      return mkGoldActionSequenceChangeState(modifiers, runner)
    } else if (mode == MODE_FREEZE) {
      return mkGoldActionSequenceChangeState(modifiers, runner)
    } else if (mode == MODE_CHANGESTATE) {
      return mkGoldActionSequenceChangeState(modifiers, runner)

    } else {
      throw new RuntimeException("ERROR: Unrecognized task mode: " + mode)
    }
  }


  def mkGoldActionSequenceChangeState(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String]) = {
    val universe = runner.agentInterface.get.universe
    val agent = runner.agentInterface.get.agent

    // Task variables
    val objectName = this.getTaskValueStr(modifiers, "objectName").get
    //val objectLocation = this.getTaskValueStr(modifiers, "location").get

    // Stage 1: Get thermometer
    // Move from starting location to get instrument (thermometer)
    val (actions, actionStrs) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = "kitchen")
    runActionSequence(actionStrs, runner)

    // Look around
    runAction("look around", runner)

    // Take instrument (thermometer)
    val instrumentName = "thermometer"
    val instruments = PathFinder.getAllAccessibleEnvObject(queryName = instrumentName, getCurrentAgentLocation(runner))
    if (instruments.length == 0) return (false, getActionHistory(runner))
    val instrument = instruments(0)
    //runAction("pick up " + PathFinder.getObjUniqueReferent(seedJar, getCurrentAgentLocation(runner)).get, runner)
    runAction("pick up " + instrument.name, runner)


    // Take a container (metal pot)
    runAction("open cupboard", runner)

    val container = getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[MetalPot]().toList(0)

    runAction("pick up " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)

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
    var taskObject:EnvObject = null
    if (objectName == "water") {
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
      var objects = PathFinder.getAllAccessibleEnvObject(queryName = objectName, getCurrentAgentLocation(runner))
      if (objects.length == 0) {

        // Try searching elsewhere
        val actionStrsSearchPattern1 = PathFinder.createActionSequenceSearchPatternPrecomputed(universe, agent, getCurrentAgentLocation(runner).name)

        // Walk around the environment until we find the thing to test
        breakable {
          for (searchPatternStep <- actionStrsSearchPattern1) {
            // First, check to see if the object is here
            val curLocSearch = PathFinder.getEnvObject(queryName = getCurrentAgentLocation(runner).name, universe) // Get a pointer to the whole room the answer box is in
            objects = PathFinder.getAllAccessibleEnvObject(queryName = objectName, getCurrentAgentLocation(runner))
            if (objects.size > 0) {
              break()
            }

            // If not found, move to next location to continue search
            runActionSequence(searchPatternStep, runner)
            runAction("look around", runner)
          }

          val curLocSearch = PathFinder.getEnvObject(queryName = getCurrentAgentLocation(runner).name, universe) // Get a pointer to the whole room the answer box is in
          objects = PathFinder.getAllAccessibleEnvObject(queryName = objectName, getCurrentAgentLocation(runner))

        }


        if (objects.length == 0) {
          //## runAction("NOTE: WAS NOT ABLE TO FIND SUBSTANCE (" + objectName + ")", runner)
          return (false, getActionHistory(runner))
        } else {
          // Pick up the object
          taskObject = objects(0)

          if (taskObject.propMaterial.get.stateOfMatter == "solid") {
            runAction("pick up " + PathFinder.getObjUniqueReferent(taskObject, getCurrentAgentLocation(runner)).get, runner)
          } else {
            runAction("pick up " + PathFinder.getObjUniqueReferent(taskObject.getContainer().get, getCurrentAgentLocation(runner)).get, runner)
          }

          // Return to kitchen
          val (actions2, actionStrs2) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = "kitchen")
          runActionSequence(actionStrs2, runner)
        }
      }

      taskObject = objects(0)


    }

    // Check it was picked up correctly
    if (PathFinder.getObjUniqueReferent(taskObject, getCurrentAgentLocation(runner)).isEmpty) {
      runAction("NODE: CAN'T FIND THE OBJECT", runner)
      return (false, getActionHistory(runner))
    }

    // Focus on task object
    runAction("focus on " + PathFinder.getObjUniqueReferent(taskObject, getCurrentAgentLocation(runner)).get, runner)


    if (taskObject.propMaterial.get.stateOfMatter == "solid") {
      // solid -- move to new container
      runAction("move " + PathFinder.getObjUniqueReferent(taskObject, getCurrentAgentLocation(runner)).get + " to " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)
    } else {
      // liquid -- pour to new container
      val oldContainer = taskObject.getContainer().get
      runAction("pour " + PathFinder.getObjUniqueReferent(oldContainer, getCurrentAgentLocation(runner)).get + " into " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)
    }


    val currentSOM = taskObject.propMaterial.get.stateOfMatter

    if (mode == MODE_MELT) {
      if (currentSOM == "solid") {
        // If a solid, start heating
        this.mkActionSequenceHeatToStateOfMatter(taskObject, container, stopAtStateOfMatter = "liquid", method = "stove", universe, agent, runner)
      } else {
        // If currently a liquid or gas, then cool until a solid, then start heating
        this.mkActionSequenceCoolToStateOfMatter(taskObject, container, stopAtStateOfMatter = "solid", method = "freezer", universe, agent, runner)
        runAction("pick up " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)
        this.mkActionSequenceHeatToStateOfMatter(taskObject, container, stopAtStateOfMatter = "liquid", method = "stove", universe, agent, runner)
      }

    } else if (mode == MODE_BOIL) {
      if (currentSOM != "gas") {
        // If currently a solid or liquid, then start heating
        this.mkActionSequenceHeatToStateOfMatter(taskObject, container, stopAtStateOfMatter = "gas", method = "stove", universe, agent, runner, isCombustionAllowed = true)
      } else {
        // If currently a gas, then cool until a liquid, then start heating
        this.mkActionSequenceCoolToStateOfMatter(taskObject, container, stopAtStateOfMatter = "liquid", method = "freezer", universe, agent, runner)
        runAction("pick up " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)
        this.mkActionSequenceHeatToStateOfMatter(taskObject, container, stopAtStateOfMatter = "gas", method = "stove", universe, agent, runner, isCombustionAllowed = true)
      }

    } else if (mode == MODE_FREEZE) {
      if (currentSOM != "solid") {
        // If currently not a solid, then cool until a solid
        this.mkActionSequenceCoolToStateOfMatter(taskObject, container, stopAtStateOfMatter = "solid", method = "freezer", universe, agent, runner)
      } else {
        // If currently a solid, then heat until a liquid, then cool
        this.mkActionSequenceHeatToStateOfMatter(taskObject, container, stopAtStateOfMatter = "liquid", method = "stove", universe, agent, runner)
        runAction("pick up " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)
        this.mkActionSequenceCoolToStateOfMatter(taskObject, container, stopAtStateOfMatter = "solid", method = "freezer", universe, agent, runner)
      }

    } else if (mode == MODE_CHANGESTATE) {
      // Any change is valid
      // Get current state of matter
      val currentSOM = taskObject.propMaterial.get.stateOfMatter

      // Change state according to current state of matter
      if (currentSOM == "solid") {
        // If a solid, try melting it
        this.mkActionSequenceHeatToStateOfMatter(taskObject, container, stopAtStateOfMatter = "liquid", method = "stove", universe, agent, runner)
      } else if (currentSOM == "gas") {
        // If a gas, try condensing it
        this.mkActionSequenceCoolToStateOfMatter(taskObject, container, stopAtStateOfMatter = "liquid", method = "freezer", universe, agent, runner)
      } else {
        // If a liquid, first try cooling it -- if that doesn't work, try heating it
        this.mkActionSequenceCoolToStateOfMatter(taskObject, container, stopAtStateOfMatter = "solid", method = "freezer", universe, agent, runner)
        if (taskObject.propMaterial.get.stateOfMatter == "liquid") {
          // Cooling didn't change the state -- try heating it
          runAction("pick up " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)
          this.mkActionSequenceHeatToStateOfMatter(taskObject, container, stopAtStateOfMatter = "gas", method = "stove", universe, agent, runner, isCombustionAllowed = true)
        }
      }

    }


    // Wait one moment
    runAction("wait1", runner)

    //## debug, add subgoals
    //runAction(runner.agentInterface.get.getGoalProgressStr(), runner)

    // Return
    return (true, getActionHistory(runner))
  }


  // Heat the substance until it becomes a (liquid / gas)
  def mkActionSequenceHeatToStateOfMatter(substance:EnvObject, container:EnvObject, stopAtStateOfMatter:String = "gas", method:String = "stove", universe:EnvObject, agent:Agent, runner:PythonInterface, isCombustionAllowed:Boolean = false): Boolean = {
    val instrumentName = "thermometer"

    //## TODO
    var activationSuccess:Boolean = false
    if (method == "stove") {
      runAction("pick up " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)

      val (actions2, actionStrs2) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = "kitchen")
      runActionSequence(actionStrs2, runner)

      // Use stove
      val heatingDeviceName:String = "stove"
      runAction("move " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get + " to " + heatingDeviceName, runner)

      runAction("activate " + heatingDeviceName, runner)

      // Check that the device activated successfully
      val heatingDevice = PathFinder.getEnvObject(heatingDeviceName, universe)
      if (heatingDevice.isDefined) {
        if (heatingDevice.get.propDevice.get.isActivated) {
          activationSuccess = true
        }
      }

    } else if (method == "blast furnace") {
      // Use blast furnace
      runAction("pick up " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)

      // Go to foundry
      val (actions2, actionStrs2) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = "foundry")
      runActionSequence(actionStrs2, runner)

      val heatingDeviceName:String = "blast furnace"
      runAction("open " + heatingDeviceName, runner)
      runAction("move " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get + " to " + heatingDeviceName, runner)

      runAction("activate " + heatingDeviceName, runner)

      // Check that the device activated successfully
      val heatingDevice = PathFinder.getEnvObject(heatingDeviceName, universe)
      if (heatingDevice.isDefined) {
        if (heatingDevice.get.propDevice.get.isActivated) {
          activationSuccess = true
        }
      }

    }

    val MAX_ITER = 30
    var objSOM = substance.propMaterial.get.stateOfMatter
    if (activationSuccess) {
      breakable {
        for (i <- 0 until MAX_ITER) {
          // Check to see object's state of matter
          println("substance: " + substance.toStringMinimal())

          // Alternatively, if combustion is allowed, also check for that
          if (isCombustionAllowed && substance.propMaterial.get.isCombusting) {
            break()
          }

          if (substance.isDeleted()) {
            //## runAction("NOTE: SUBSTANCE HAS BEEN DELETED, LIKELY AS A RESULT OF COMBUSTING", runner)
            return false
          }

          runAction("examine " + PathFinder.getObjUniqueReferent(substance, getCurrentAgentLocation(runner)).get, runner)
          objSOM = substance.propMaterial.get.stateOfMatter

          if (substance.isDeleted()) {
            //## runAction("NOTE: SUBSTANCE HAS BEEN DELETED, LIKELY AS A RESULT OF COMBUSTING", runner)
            return false
          }

          // Measure object temperature
          val objTempC = substance.propMaterial.get.temperatureC
          runAction("use " + instrumentName + " in inventory on " + PathFinder.getObjUniqueReferent(substance, getCurrentAgentLocation(runner)).get, runner)

          // Wait 10 steps
          //runAction("wait", runner)

          // Break when the object is no longer a liquid
          //## runAction("NOTE: STATE OF MATTER " + objSOM + " / " + stopAtStateOfMatter, runner)
          if (objSOM == stopAtStateOfMatter) break()

        }
      }
    }

    if (objSOM != stopAtStateOfMatter) {
      // Check for special case of combustion
      if (isCombustionAllowed && substance.propMaterial.get.isCombusting) {
        return true
      }

      // It didn't work, try a backoff strategy
      if (method == "stove") {
        // Try the blast furnace
        return mkActionSequenceHeatToStateOfMatter(substance, container, stopAtStateOfMatter, method = "blast furnace", universe, agent, runner)
      }


      // If we reach here, the process didn't work
      return false
    }

    // If we reach here, the process worked
    return true
  }

  def mkActionSequenceCoolToStateOfMatter(substance:EnvObject, container:EnvObject, stopAtStateOfMatter:String = "solid", method:String = "freezer", universe:EnvObject, agent:Agent, runner:PythonInterface): Boolean = {
    val instrumentName = "thermometer"

    val (actions2, actionStrs2) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = "kitchen")
    runActionSequence(actionStrs2, runner)

    // Use freezer
    if (method == "freezer") {
      runAction("pick up " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)

      val (actions2, actionStrs2) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = "kitchen")
      runActionSequence(actionStrs2, runner)

      val coolingDeviceName: String = "freezer"
      runAction("open " + coolingDeviceName, runner)
      runAction("move " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get + " to " + coolingDeviceName, runner)

    } else if (method == "ultfreezer") {
      runAction("pick up " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get, runner)

      val (actions2, actionStrs2) = PathFinder.createActionSequence(universe, agent, startLocation = getCurrentAgentLocation(runner).name, endLocation = "workshop")
      runActionSequence(actionStrs2, runner)

      val coolingDeviceName: String = "freezer"
      runAction("open " + coolingDeviceName, runner)
      runAction("move " + PathFinder.getObjUniqueReferent(container, getCurrentAgentLocation(runner)).get + " to " + coolingDeviceName, runner)

    }

    val MAX_ITER = 20
    var objSOM = substance.propMaterial.get.stateOfMatter
    breakable {
      for (i <- 0 until MAX_ITER) {
        if (substance.isDeleted()) {
          //## runAction("NOTE: SUBSTANCE HAS BEEN DELETED, LIKELY AS A RESULT OF COMBUSTING", runner)
          return false
        }

        // Check to see object's state of matter
        runAction("examine " + PathFinder.getObjUniqueReferent(substance, getCurrentAgentLocation(runner)).get, runner)
        objSOM = substance.propMaterial.get.stateOfMatter

        if (substance.isDeleted()) {
          //## runAction("NOTE: SUBSTANCE HAS BEEN DELETED, LIKELY AS A RESULT OF COMBUSTING", runner)
          return false
        }
        // Measure object temperature
        val objTempC = substance.propMaterial.get.temperatureC
        runAction("use " + instrumentName + " in inventory on " + PathFinder.getObjUniqueReferent(substance, getCurrentAgentLocation(runner)).get, runner)

        if (substance.isDeleted()) {
          //## runAction("NOTE: SUBSTANCE HAS BEEN DELETED, LIKELY AS A RESULT OF COMBUSTING", runner)
          return false
        }

        // Wait 10 steps
        runAction("wait", runner)

        // Break when the object is no longer a liquid
        //## runAction("NOTE: STATE OF MATTER " + objSOM + " / " + stopAtStateOfMatter, runner)
        if (objSOM == stopAtStateOfMatter) break()
      }
    }

    if (objSOM != stopAtStateOfMatter) {
      // It didn't work, try a backoff strategy
      if (method == "freezer") {
        // Try the blast furnace
        return mkActionSequenceCoolToStateOfMatter(substance, container, stopAtStateOfMatter, method = "ultfreezer", universe, agent, runner)
      }


      // If we reach here, the process didn't work
      return false
    }

    // If we reach here, the process worked
    return true

  }

}


object TaskChangeOfState {
  val MODE_CHANGESTATE  = "change the state of matter of"
  val MODE_MELT         = "melt"
  val MODE_BOIL         = "boil"
  val MODE_FREEZE       = "freeze"


  def registerTasks(taskMaker:TaskMaker1): Unit = {
    taskMaker.addTask( new TaskChangeOfState(mode = MODE_CHANGESTATE) )
    taskMaker.addTask( new TaskChangeOfState(mode = MODE_MELT) )
    taskMaker.addTask( new TaskChangeOfState(mode = MODE_BOIL) )
    taskMaker.addTask( new TaskChangeOfState(mode = MODE_FREEZE) )
  }

  // Make an unknown substance, and put it in a container if it's a liquid
  def mkSubstanceInContainer(substance:EnvObject):EnvObject = {
    // Put in a container
    return ContainerMaker.mkRandomLiquidCup(substance)
  }


}
