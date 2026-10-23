package scienceworld.tasks.specifictasks

import scienceworld.actions.Action
import scienceworld.goldagent.PathFinder
import scienceworld.objects.agent.Agent
import scienceworld.objects.electricalcomponent.{Battery, ElectricBuzzer, ElectricMotor, LightBulb, PolarizedElectricalComponent, UnpolarizedElectricalComponent, Wire}
import scienceworld.objects.misc.{ForkMetal, ForkPlastic}
import scienceworld.objects.substance.{SodiumChloride, Water}
import scienceworld.objects.taskitems.{AnswerBox, UnknownSubstanceElectricalConductivity}
import scienceworld.runtime.pythonapi.PythonInterface
import scienceworld.struct.EnvObject
import scienceworld.tasks.{Task, TaskMaker1, TaskModifier, TaskObject, TaskValueBool, TaskValueStr}
import scienceworld.tasks.goals.{Goal, GoalSequence}
import scienceworld.tasks.goals.specificgoals.{GoalFind, GoalInRoomWithObject, GoalMoveToNewLocation, GoalObjectConnectedToWire, GoalObjectInContainerByName, GoalWireConnectsObjectAndAnyLightBulb, GoalWireConnectsObjectAndAnyPowerSource, GoalWireConnectsPowerSourceAndAnyLightBulb}
import scienceworld.tasks.specifictasks.TaskElectricalConductivity2.MODE_TEST_CONDUCTIVITY_UNKNOWN

import scala.collection.mutable.ArrayBuffer
import scala.util.Random
import scala.util.control.Breaks.{break, breakable}

class TaskElectricalConductivity2(val mode:String = MODE_TEST_CONDUCTIVITY_UNKNOWN) extends TaskParametric {
  val taskName = mode.replaceAll(" ", "-").replaceAll("[()]", "")

  val locations = Array("workshop")
  val substanceLocations = Array("workshop", "kitchen", "living room")

  // Variation 1: Battery
  val powerSource = new ArrayBuffer[ Array[TaskModifier] ]()
  for (location <- locations) {
    val battery = new Battery()
    powerSource.append(Array(
      new TaskObject(battery.name, Some(battery), roomToGenerateIn = location, Array.empty[String], generateNear = 0)
    ))
  }

  // Variation 2: Part to power
  val partToPower = new ArrayBuffer[ Array[TaskModifier] ]()
  val lightColors = Array("red", "green", "blue")

  for (location <- locations) {
    for (color <- lightColors) {
      val lightbulb = new LightBulb(color)
      partToPower.append( Array( new TaskObject(lightbulb.name, Some(lightbulb), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
        new TaskValueStr(key = "partToPower", value = lightbulb.name) ))

    }
    // Additional parts (motor)
    val electricMotor = new ElectricMotor()
    partToPower.append( Array(new TaskObject(electricMotor.name, Some(electricMotor), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
      new TaskValueStr(key = "partToPower", value = electricMotor.name) ))

    // Additional parts (buzzer)
    val electricBuzzer = new ElectricBuzzer()
    partToPower.append( Array(new TaskObject(electricBuzzer.name, Some(electricBuzzer), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
      new TaskValueStr(key = "partToPower", value = electricBuzzer.name) ))
  }

  // Variation 3: Substance to test
  val unknownSubstances = new ArrayBuffer[ Array[TaskModifier] ]()
  for (location <- locations) {
    val validLetters = Array("B", "C", "D", "E", "F", "G", "H", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z")
    for (validLetter <- validLetters) {
      val unknownSubstance = UnknownSubstanceElectricalConductivity.mkRandomSubstanceElectricalConductive(validLetter)
      unknownSubstances.append(Array(
        new TaskObject(unknownSubstance.name, Some(unknownSubstance), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
        new TaskValueStr(key = "unknownSubstance", value = unknownSubstance.name),
        new TaskValueStr(key = "substanceLocation", value = location),
        new TaskValueBool(key = "unknownIsConductive", value = unknownSubstance.propMaterial.get.electricallyConductive)
      ))
    }
  }
  // Make sure the list is sorted by substance instead of location, so that the unseen sets have new substances
  val unknownSubstancesSorted = unknownSubstances.sortBy(getTaskValueStr(_, key = "unknownSubstance"))


  // Variation 4: Answer boxes
  val answerBoxes = new ArrayBuffer[ Array[TaskModifier] ]()
  val answerBoxColors = Array("red", "green", "blue", "orange", "yellow", "purple")
  for (location <- locations) {
    for (i <- 0 until answerBoxColors.length-1) {
      val colorConductive = answerBoxColors(i)
      val colorNonconductive = answerBoxColors(i+1)
      val boxC = new AnswerBox(colorConductive)
      val boxNC = new AnswerBox(colorNonconductive)
      answerBoxes.append(Array(
        new TaskObject(boxC.name, Some(boxC), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
        new TaskObject(boxNC.name, Some(boxNC), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
        new TaskValueStr(key = "conductive", boxC.name),
        new TaskValueStr(key = "nonconductive", boxNC.name)
      ))
    }
  }

  // Combinations
  val combinations = for {
    m <- unknownSubstancesSorted
    i <- powerSource
    j <- partToPower
    n <- answerBoxes
  } yield List(i, j, m, n)

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
    val boxNameConductive = this.getTaskValueStr(modifiers, "conductive")
    val boxNameNonconductive = this.getTaskValueStr(modifiers, "nonconductive")
    val unknownSubstanceName = this.getTaskValueStr(modifiers, "unknownSubstance")
    val unknownSubstanceConductive = this.getTaskValueBool(modifiers, "unknownIsConductive")
    val specificSubstanceName = this.getTaskValueStr(modifiers, "substance")
    val specificSubstanceLocation = this.getTaskValueStr(modifiers, "substanceLocation")
    val specificSubstanceConductive = this.getTaskValueBool(modifiers, key = "isConductive")


    var subTask = ""
    val gSequence = new ArrayBuffer[Goal]
    val gSequenceUnordered = new ArrayBuffer[Goal]()
    var description:String = "<empty>"

    if (mode == MODE_TEST_CONDUCTIVITY_UNKNOWN) {
      // Figure out the correct answer container based on the object's conductivity
      var correctContainerName: String = ""
      var incorrectContainerName: String = ""
      if (unknownSubstanceConductive.get == true) {
        // Object is conductive
        correctContainerName = boxNameConductive.get
        incorrectContainerName = boxNameNonconductive.get
      } else {
        // Object is non-conductive
        correctContainerName = boxNameNonconductive.get
        incorrectContainerName = boxNameConductive.get
      }

      // Goal sequence
      gSequence.append(new GoalFind(objectName = unknownSubstanceName.get, failIfWrong = true, description = "focus on task object"))
      gSequence.append(new GoalObjectInContainerByName(containerName = correctContainerName, failureContainers = List(incorrectContainerName), description = "put object in correct container")) // Then, make sure it's in the correct answer container

      // Unordered
      gSequenceUnordered.append(new GoalMoveToNewLocation(_isOptional = true, unlessInLocation = "", description = "move to a new location") )            // Move to any new location
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = unknownSubstanceName.get, _isOptional = true, description = "be in same location as part to power"))

      // Connect the component to a wire on either side
      gSequenceUnordered.append(new GoalObjectConnectedToWire(unknownSubstanceName.get, terminal1 = true, terminal2 = false, anode = true, cathode = false, description = "connect the task object's (terminal1/anode) to a wire"))
      gSequenceUnordered.append(new GoalObjectConnectedToWire(unknownSubstanceName.get, terminal1 = false, terminal2 = true, anode = false, cathode = true, description = "connect the task object's (terminal2/cathode) to a wire"))

      // Connect a wire between at least one side of the component, and one side of the correct power source (e.g. solar panel)
      gSequenceUnordered.append(new GoalWireConnectsObjectAndAnyPowerSource(unknownSubstanceName.get, "", description = "task object is at least partially connected to power source through wire"))
      gSequenceUnordered.append(new GoalWireConnectsObjectAndAnyLightBulb(unknownSubstanceName.get, "", description = "task object is at least partially connected to a light bulb through wire"))
      gSequenceUnordered.append(new GoalWireConnectsPowerSourceAndAnyLightBulb(description = "light bulb is at least partially connected to a power source through wire"))

      // TODO: Add more example substances for the named task
      // TODO: Add distractors?


      // Description
      description = "Your task is to determine if " + unknownSubstanceName.get + " is electrically conductive. "
      description += "The " + unknownSubstanceName.get + " is located around the " + specificSubstanceLocation.get + ". "
      description += "First, focus on the " + unknownSubstanceName.get + ". "
      description += "If it is electrically conductive, place it in the " + boxNameConductive.get + ". "
      description += "If it is electrically nonconductive, place it in the " + boxNameNonconductive.get + ". "

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
    if (mode == MODE_TEST_CONDUCTIVITY_UNKNOWN) {
      return mkGoldActionSequenceTestComponent(modifiers, runner)
    } else {
      throw new RuntimeException("ERROR: Unrecognized task mode: " + mode)
    }

  }

  /*
   * Gold action sequences
   */
  def mkGoldActionSequenceTestComponent(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String]) = {
    val universe = runner.agentInterface.get.universe
    val agent = runner.agentInterface.get.agent

    // Task variables
    val boxNameConductive = this.getTaskValueStr(modifiers, "conductive")
    val boxNameNonconductive = this.getTaskValueStr(modifiers, "nonconductive")
    val unknownSubstanceName = this.getTaskValueStr(modifiers, "unknownSubstance")
    val unknownSubstanceConductive = this.getTaskValueBool(modifiers, "unknownIsConductive")
    //val specificSubstanceName = this.getTaskValueStr(modifiers, "substance")
    val specificSubstanceConductive = this.getTaskValueBool(modifiers, key = "isConductive")
    val partToPower = this.getTaskValueStr(modifiers, "partToPower")


    // Step 1: Find the substance
    val startLocation1 = agent.getContainer().get.name
    //val actionStrsSearchPattern1 = PathFinder.createActionSequenceSearchPattern(universe, agent, startLocation1)
    val actionStrsSearchPattern1 = PathFinder.createActionSequenceSearchPatternPrecomputed(universe, agent, startLocation1)

    var substance:Option[EnvObject] = None
    var substanceContainer:Option[EnvObject] = None

    // Walk around the environment until we find the thing to test
    breakable {
      for (searchPatternStep <- actionStrsSearchPattern1) {
        // First, check to see if the object is here
        val curLocSearch = PathFinder.getEnvObject(queryName = getCurrentAgentLocation(runner).name, universe) // Get a pointer to the whole room the answer box is in
        val substance_ = PathFinder.getAllAccessibleEnvObject(unknownSubstanceName.get, curLocSearch.get)

        if (substance_.length > 0) {
          // Substance likely found -- try to pick it up
          substance = Some(substance_(0))
          // If it's not a solid, then pick up it's container
          if ((substance.get.propMaterial.isDefined) && (substance.get.propMaterial.get.stateOfMatter != "solid")) {
            // Assume liquid, pick up container
            // TODO: Check that container is movable.
            substanceContainer = substance.get.getContainer()
            runAction("pick up " + PathFinder.getObjUniqueReferent(substance.get, getCurrentAgentLocation(runner)).get, runner)

          } else {
            // Assume solid, pick up thing
            substanceContainer = substance // Container is itself, since it's the thing we'll be 'moving' to the workshop to test conductivity
            runAction("pick up " + PathFinder.getObjUniqueReferent(substanceContainer.get, getCurrentAgentLocation(runner)).get, runner)
          }

          // If we reach here, we've found and picked up the substance
          break
        }

        // If not found, move to next location to continue search
        runActionSequence(searchPatternStep, runner)
      }

      // Edge case: Substance is found at the end of the path
      val curLocSearch = PathFinder.getEnvObject(queryName = getCurrentAgentLocation(runner).name, universe) // Get a pointer to the whole room the answer box is in
      val substance_ = PathFinder.getAllAccessibleEnvObject(unknownSubstanceName.get, curLocSearch.get)
      if (substance_.length > 0) {
        // Substance likely found -- try to pick it up
        substance = Some(substance_(0))
        // If it's not a solid, then pick up it's container
        if ((substance.get.propMaterial.isDefined) && (substance.get.propMaterial.get.stateOfMatter != "solid")) {
          // Assume liquid, pick up container
          // TODO: Check that container is movable.
          substanceContainer = substance.get.getContainer()
          runAction("pick up " + PathFinder.getObjUniqueReferent(substance.get, getCurrentAgentLocation(runner)).get, runner)

        } else {
          // Assume solid, pick up thing
          substanceContainer = substance // Container is itself, since it's the thing we'll be 'moving' to the workshop to test conductivity
          runAction("pick up " + PathFinder.getObjUniqueReferent(substanceContainer.get, getCurrentAgentLocation(runner)).get, runner)
        }
      }

    }

    // Check that we successfully found the substance -- if not, fail
    if (substanceContainer.isEmpty) {
      // Fail
      return (false, getActionHistory(runner))
    }

    // Step 2: Focus on substance
    runAction("focus on " + PathFinder.getObjUniqueReferent(substance.get, getCurrentAgentLocation(runner)).get, runner)


    // Step 3: Move from current location to workshop
    val partLocation = "workshop"
    val curLoc = agent.getContainer().get.name
    val (actions, actionStrs) = PathFinder.createActionSequence(universe, agent, startLocation = curLoc, endLocation = partLocation)
    runActionSequence(actionStrs, runner)

    // Step 4: Drop substance
    val nameOfThingToDrop = PathFinder.getObjUniqueReferent(substanceContainer.get, agent)      //## TODO: Fails on getting container sometimes, for some reason.  (probably not movable, so wasn't picked up in the first place)
    if (nameOfThingToDrop.isEmpty) {
      // Fail
      return (false, getActionHistory(runner))
    }
    runAction("drop " + nameOfThingToDrop.get, runner)

    // Step 4A: Look around
    val (actionLook, actionLookStr) = PathFinder.actionLookAround(agent)
    runAction(actionLookStr, runner)


    // Step 1B: Look at part to power (TODO)



    // Step 5: Get references to parts
    val curLoc1 = PathFinder.getEnvObject(queryName = getCurrentAgentLocation(runner).name, universe)    // Get a pointer to the whole room the answer box is in
    val objsInRoom = curLoc1.get.getContainedObjectsRecursiveAccessible(includeHidden = false)

    // Part to power
    val component = PathFinder.getAllAccessibleEnvObject(partToPower.get, curLoc1.get)(0)

    // Parts to use to power
    val battery = curLoc1.get.getContainedAccessibleObjectsOfType[Battery](includeHidden = false)
    val wires = Random.shuffle( curLoc1.get.getContainedAccessibleObjectsOfType[Wire](includeHidden = false).toList.sortBy(_.uuid) )
    if (wires.size < 3) {
      // Fail
      return (false, getActionHistory(runner))
    }

    val wire1 = wires(0)
    val wire2 = wires(1)
    val wire3 = wires(2)

    // Do connections

    // Connect battery to wires
    runAction("connect battery anode to " + PathFinder.getObjUniqueReferent(wire1, getCurrentAgentLocation(runner)).get + " terminal 1", runner)
    runAction("connect battery cathode to " + PathFinder.getObjUniqueReferent(wire2, getCurrentAgentLocation(runner)).get + " terminal 1", runner)

    // Connect wires to actuator
    var anodeReferent:String = ""
    var cathodeReferent:String = ""
    component match {
      case p:PolarizedElectricalComponent => {
        anodeReferent = PathFinder.getObjUniqueReferent(p.anode, getCurrentAgentLocation(runner)).get
        cathodeReferent = PathFinder.getObjUniqueReferent(p.cathode, getCurrentAgentLocation(runner)).get
      }
      case u:UnpolarizedElectricalComponent => {
        anodeReferent = PathFinder.getObjUniqueReferent(u.terminal1.get, getCurrentAgentLocation(runner)).get
        cathodeReferent = PathFinder.getObjUniqueReferent(u.terminal2.get, getCurrentAgentLocation(runner)).get
      }
      case _ => {
        // This should never happen?
      }
    }
    runAction("connect " + PathFinder.getObjUniqueReferent(wire1, getCurrentAgentLocation(runner)).get + " terminal 2 to " + cathodeReferent, runner)   // to device cathode
    runAction("connect " + PathFinder.getObjUniqueReferent(wire3, getCurrentAgentLocation(runner)).get + " terminal 2 to " + anodeReferent, runner)   // to device anode

    // Connect substance to test
    runAction("connect " + substance.get.name + " terminal 1 to " + PathFinder.getObjUniqueReferent(wire2, getCurrentAgentLocation(runner)).get + " terminal 2", runner)
    runAction("connect " + substance.get.name + " terminal 2 to " + PathFinder.getObjUniqueReferent(wire3, getCurrentAgentLocation(runner)).get + " terminal 1", runner)


    // Wait one moment, for the power to cycle
    runAction("wait1", runner)
    runAction("wait1", runner)


    // Step N: Check to see if the actuator is on or not


    // Look around
    runAction("look around", runner)

    var isConductive:Boolean = false
    if ((component.propDevice.isDefined) && (component.propDevice.get.isActivated == true)) {
      isConductive = true
    }

    val boxConductive = PathFinder.getAllAccessibleEnvObject(boxNameConductive.get, curLoc1.get)(0)
    val boxNonconductive = PathFinder.getAllAccessibleEnvObject(boxNameNonconductive.get, curLoc1.get)(0)
    if (isConductive) {
      runAction("move " + substance.get.name + " to " + PathFinder.getObjUniqueReferent(boxConductive, getCurrentAgentLocation(runner)).get, runner)
    } else {
      runAction("move " + substance.get.name + " to " + PathFinder.getObjUniqueReferent(boxNonconductive, getCurrentAgentLocation(runner)).get, runner)
    }

    // Wait one moment
    runAction("wait1", runner)

    // Return
    return (true, getActionHistory(runner))
  }

}


object TaskElectricalConductivity2 {
  val MODE_TEST_CONDUCTIVITY_UNKNOWN    = "test conductivity of unknown substances"

  def registerTasks(taskMaker:TaskMaker1): Unit = {
    taskMaker.addTask( new TaskElectricalConductivity2(mode = MODE_TEST_CONDUCTIVITY_UNKNOWN) )
  }

}
