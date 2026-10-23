package scienceworld.tasks.specifictasks

import scienceworld.actions.Action
import scienceworld.goldagent.PathFinder
import scienceworld.objects.agent.Agent
import scienceworld.objects.containers.{GlassJar, MetalPot}
import scienceworld.objects.devices.Shovel
import scienceworld.objects.document.BookOriginOfSpecies
import scienceworld.objects.electricalcomponent.{Battery, ElectricBuzzer, ElectricMotor, GasGenerator, LightBulb, NuclearGenerator, PolarizedElectricalComponent, SolarPanel, UnpolarizedElectricalComponent, WindGenerator, Wire}
import scienceworld.objects.misc.{AluminumFoil, ForkMetal, ForkPlastic, PaperClip}
import scienceworld.objects.substance.food.Apricot
import scienceworld.objects.substance.{SodiumChloride, Water, WoodBlock}
import scienceworld.objects.taskitems.{AnswerBox, UnknownSubstanceElectricalConductivity}
import scienceworld.runtime.pythonapi.PythonInterface
import scienceworld.struct.EnvObject
import scienceworld.tasks.{Task, TaskMaker1, TaskModifier, TaskObject, TaskValueBool, TaskValueStr}
import scienceworld.tasks.goals.{Goal, GoalSequence}
import scienceworld.tasks.goals.specificgoals.{GoalActivateDevice, GoalElectricallyConnected, GoalFind, GoalInRoomWithObject, GoalMoveToNewLocation, GoalObjectConnectedToWire, GoalObjectInContainer, GoalObjectInContainerByName, GoalWireConnectsObjectAndAnyLightBulb, GoalWireConnectsObjectAndAnyPowerSource, GoalWireConnectsPowerSourceAndAnyLightBulb}
import scienceworld.tasks.specifictasks.TaskElectricalConductivity.MODE_TEST_CONDUCTIVITY

import scala.collection.mutable.ArrayBuffer
import scala.util.Random
import scala.util.control.Breaks._


class TaskElectricalConductivity(val mode:String = MODE_TEST_CONDUCTIVITY) extends TaskParametric {
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
      new TaskValueStr(key = "partToPower", value = electricBuzzer.name)))
  }

  // Variation 3: Substance to test
  val substanceToTest = new ArrayBuffer[ Array[TaskModifier] ]()
  for (location <- substanceLocations) {
    // Substance 1: Salt
    val salt = new SodiumChloride()
    substanceToTest.append(Array(
      new TaskObject(salt.name, Some(salt), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
      new TaskValueStr(key = "substance", value = salt.name),
      new TaskValueStr(key = "substanceLocation", value = location),
      new TaskValueBool(key = "isConductive", value = salt.propMaterial.get.electricallyConductive)
    ))

    // Substance 2: Water
    val water = new Water()
    substanceToTest.append(Array(
      //new TaskObject(salt.name, Some(salt), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
      new TaskValueStr(key = "substance", value = water.name),
      new TaskValueStr(key = "substanceLocation", value = location),
      new TaskValueBool(key = "isConductive", value = water.propMaterial.get.electricallyConductive)
    ))

    // Substance 3: Plastic fork
    val plasticfork = new ForkPlastic()
    substanceToTest.append(Array(
      new TaskObject(plasticfork.name, Some(plasticfork), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
      new TaskValueStr(key = "substance", value = plasticfork.name),
      new TaskValueStr(key = "substanceLocation", value = location),
      new TaskValueBool(key = "isConductive", value = plasticfork.propMaterial.get.electricallyConductive)
    ))

    // Substance 4: Metal fork
    val metalfork = new ForkMetal()
    substanceToTest.append(Array(
      new TaskObject(metalfork.name, Some(metalfork), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
      new TaskValueStr(key = "substance", value = metalfork.name),
      new TaskValueStr(key = "substanceLocation", value = location),
      new TaskValueBool(key = "isConductive", value = metalfork.propMaterial.get.electricallyConductive)
    ))

    // Substance 5: Apricot
    val apricot = new Apricot()
    substanceToTest.append(Array(
      new TaskObject(apricot.name, Some(apricot), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
      new TaskValueStr(key = "substance", value = apricot.name),
      new TaskValueStr(key = "substanceLocation", value = location),
      new TaskValueBool(key = "isConductive", value = apricot.propMaterial.get.electricallyConductive)
    ))

    // Substance 6: Shovel
    val shovel = new Shovel()
    substanceToTest.append(Array(
      new TaskObject(shovel.name, Some(shovel), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
      new TaskValueStr(key = "substance", value = shovel.name),
      new TaskValueStr(key = "substanceLocation", value = location),
      new TaskValueBool(key = "isConductive", value = shovel.propMaterial.get.electricallyConductive)
    ))

    // Substance 7: Glass jar
    val glassjar = new GlassJar()
    substanceToTest.append(Array(
      new TaskObject(glassjar.name, Some(glassjar), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
      new TaskValueStr(key = "substance", value = glassjar.name),
      new TaskValueStr(key = "substanceLocation", value = location),
      new TaskValueBool(key = "isConductive", value = glassjar.propMaterial.get.electricallyConductive)
    ))

    // Substance 8: Metal pot
    val metalpot = new MetalPot()
    substanceToTest.append(Array(
      new TaskObject(metalpot.name, Some(metalpot), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
      new TaskValueStr(key = "substance", value = metalpot.name),
      new TaskValueStr(key = "substanceLocation", value = location),
      new TaskValueBool(key = "isConductive", value = metalpot.propMaterial.get.electricallyConductive)
    ))

    // Substance 9: Drawing
    val book = new BookOriginOfSpecies()
    substanceToTest.append(Array(
      new TaskObject(book.name, Some(book), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
      new TaskValueStr(key = "substance", value = book.name),
      new TaskValueStr(key = "substanceLocation", value = location),
      new TaskValueBool(key = "isConductive", value = book.propMaterial.get.electricallyConductive)
    ))

    // Substance 10: Paper Clip
    val paperclip = new PaperClip()
    substanceToTest.append(Array(
      new TaskObject(paperclip.name, Some(paperclip), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
      new TaskValueStr(key = "substance", value = paperclip.name),
      new TaskValueStr(key = "substanceLocation", value = location),
      new TaskValueBool(key = "isConductive", value = paperclip.propMaterial.get.electricallyConductive)
    ))

    // Substance 11: Wood Block
    val woodblock = new WoodBlock()
    substanceToTest.append(Array(
      new TaskObject(woodblock.name, Some(woodblock), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
      new TaskValueStr(key = "substance", value = woodblock.name),
      new TaskValueStr(key = "substanceLocation", value = location),
      new TaskValueBool(key = "isConductive", value = woodblock.propMaterial.get.electricallyConductive)
    ))

    // Substance 12: Aluminum Foil
    val aluminumfoil = new AluminumFoil()
    substanceToTest.append(Array(
      new TaskObject(aluminumfoil.name, Some(aluminumfoil), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
      new TaskValueStr(key = "substance", value = aluminumfoil.name),
      new TaskValueStr(key = "substanceLocation", value = location),
      new TaskValueBool(key = "isConductive", value = aluminumfoil.propMaterial.get.electricallyConductive)
    ))
  }
  // Make sure the list is sorted by substance instead of location, so that the unseen sets have new substances
  val substancetoTestSorted = substanceToTest.sortBy(getTaskValueStr(_, key = "substance"))

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
    n <- substancetoTestSorted
    i <- powerSource
    j <- partToPower
    k <- answerBoxes
  } yield List(i, j, k, n)

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
    if (mode == MODE_TEST_CONDUCTIVITY) {
      // Figure out the correct answer container based on the object's conductivity
      var correctContainerName: String = ""
      var incorrectContainerName: String = ""
      if (specificSubstanceConductive.get == true) {
        // Object is conductive
        correctContainerName = boxNameConductive.get
        incorrectContainerName = boxNameNonconductive.get
      } else {
        // Object is non-conductive
        correctContainerName = boxNameNonconductive.get
        incorrectContainerName = boxNameConductive.get
      }

      // Goal sequence
      gSequence.append(new GoalFind(objectName = specificSubstanceName.get, failIfWrong = true, description = "focus on task object"))
      gSequence.append(new GoalObjectInContainerByName(containerName = correctContainerName, failureContainers = List(incorrectContainerName), description = "put object in correct container")) // Then, make sure it's in the correct answer container


      // Unordered
      gSequenceUnordered.append(new GoalMoveToNewLocation(_isOptional = true, unlessInLocation = "", description = "move to a new location") )            // Move to any new location
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = specificSubstanceName.get, _isOptional = true, description = "be in same location as part to power"))

      // Connect the component to a wire on either side
      gSequenceUnordered.append(new GoalObjectConnectedToWire(specificSubstanceName.get, terminal1 = true, terminal2 = false, anode = true, cathode = false, description = "connect the task object's (terminal1/anode) to a wire"))
      gSequenceUnordered.append(new GoalObjectConnectedToWire(specificSubstanceName.get, terminal1 = false, terminal2 = true, anode = false, cathode = true, description = "connect the task object's (terminal2/cathode) to a wire"))

      // Connect a wire between at least one side of the component, and one side of the correct power source (e.g. solar panel)
      gSequenceUnordered.append(new GoalWireConnectsObjectAndAnyPowerSource(specificSubstanceName.get, "", description = "task object is at least partially connected to power source through wire"))
      gSequenceUnordered.append(new GoalWireConnectsObjectAndAnyLightBulb(specificSubstanceName.get, "", description = "task object is at least partially connected to a light bulb through wire"))
      gSequenceUnordered.append(new GoalWireConnectsPowerSourceAndAnyLightBulb(description = "light bulb is at least partially connected to a power source through wire"))


      // Description
      description = "Your task is to determine if " + specificSubstanceName.get + " is electrically conductive. "
      description += "The " + specificSubstanceName.get + " is located around the " + specificSubstanceLocation.get + ". "
      description += "First, focus on the " + specificSubstanceName.get + ". "
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
    if (mode == MODE_TEST_CONDUCTIVITY) {
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
    val specificSubstanceName = this.getTaskValueStr(modifiers, "substance")
    val specificSubstanceConductive = this.getTaskValueBool(modifiers, key = "isConductive")
    val partToPower = this.getTaskValueStr(modifiers, "partToPower")


    // Step 1: Find the substance
    val startLocation1 = agent.getContainer().get.name
    //val actionStrsSearchPattern1 = PathFinder.createActionSequenceSearchPattern(universe, agent, startLocation1)
    val actionStrsSearchPattern1 = PathFinder.createActionSequenceSearchPatternPrecomputed(universe, agent, startLocation1)

    var substance:Option[EnvObject] = None
    var substanceContainer:Option[EnvObject] = None
    if (specificSubstanceName.get == "water") {
      breakable {
        // Attempt to find water
        var (success, waterContainer, waterRef) = PathFinder.getWaterInContainer(runner)

        if (!success) {
          //## runAction("NOTE: WAS NOT ABLE TO FIND WATER", runner)

          // Try searching elsewhere
          val actionStrsSearchPattern1 = PathFinder.createActionSequenceSearchPatternPrecomputed(universe, agent, getCurrentAgentLocation(runner).name)

          // Walk around the environment until we find the thing to test
          breakable {
            for (searchPatternStep <- actionStrsSearchPattern1) {
              // First, check to see if the object is here
              val (success1, waterContainer1, waterRef1) = PathFinder.getWaterInContainer(runner)
              if (success1) {
                substance = waterRef1
                substanceContainer = waterContainer1
                break()
              }

              // If not found, move to next location to continue search
              runActionSequence(searchPatternStep, runner)
              runAction("look around", runner)
            }

            val (success1, waterContainer1, waterRef1) = PathFinder.getWaterInContainer(runner)
            if (!success1) {
              //## runAction("NOTE: WAS NOT ABLE TO FIND WATER", runner)
              return (false, getActionHistory(runner))
            }
            substance = waterRef1
            substanceContainer = waterContainer1
          }

        } else {
          substance = waterRef
          substanceContainer = waterContainer
        }

        runAction("pick up " + PathFinder.getObjUniqueReferent(substanceContainer.get, getCurrentAgentLocation(runner)).get, runner)
      }

    } else {
      // Walk around the environment until we find the thing to test
      breakable {
        for (searchPatternStep <- actionStrsSearchPattern1) {
          // First, check to see if the object is here
          val curLocSearch = PathFinder.getEnvObject(queryName = getCurrentAgentLocation(runner).name, universe) // Get a pointer to the whole room the answer box is in
          val substance_ = PathFinder.getAllAccessibleEnvObject(specificSubstanceName.get, curLocSearch.get)

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
        val substance_ = PathFinder.getAllAccessibleEnvObject(specificSubstanceName.get, curLocSearch.get)
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
    if ((substance.get.propMaterial.isEmpty) || (substance.get.propMaterial.get.stateOfMatter == "solid")) {
      runAction("connect " + PathFinder.getObjUniqueReferent(substance.get, getCurrentAgentLocation(runner)).get + " terminal 1 to " + PathFinder.getObjUniqueReferent(wire2, getCurrentAgentLocation(runner)).get + " terminal 2", runner)
      runAction("connect " + PathFinder.getObjUniqueReferent(substance.get, getCurrentAgentLocation(runner)).get + " terminal 2 to " + PathFinder.getObjUniqueReferent(wire3, getCurrentAgentLocation(runner)).get + " terminal 1", runner)
    } else {
      // liquid
      runAction("connect " + substance.get.name + " terminal 1 to " + PathFinder.getObjUniqueReferent(wire2, getCurrentAgentLocation(runner)).get + " terminal 2", runner)
      runAction("connect " + substance.get.name + " terminal 2 to " + PathFinder.getObjUniqueReferent(wire3, getCurrentAgentLocation(runner)).get + " terminal 1", runner)

    }


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
      if ((substance.get.propMaterial.isEmpty) || (substance.get.propMaterial.get.stateOfMatter == "solid")) {
        runAction("move " + PathFinder.getObjUniqueReferent(substance.get, getCurrentAgentLocation(runner)).get + " to " + PathFinder.getObjUniqueReferent(boxConductive, getCurrentAgentLocation(runner)).get, runner)
      } else {
        // liquid
        runAction("move " + PathFinder.getObjUniqueReferent(substance.get.getContainer().get, getCurrentAgentLocation(runner)).get + " to " + PathFinder.getObjUniqueReferent(boxConductive, getCurrentAgentLocation(runner)).get, runner)
      }
    } else {
      if ((substance.get.propMaterial.isEmpty) || (substance.get.propMaterial.get.stateOfMatter == "solid")) {
        runAction("move " + PathFinder.getObjUniqueReferent(substance.get, getCurrentAgentLocation(runner)).get + " to " + PathFinder.getObjUniqueReferent(boxNonconductive, getCurrentAgentLocation(runner)).get, runner)
      } else {
        // liquid
        runAction("move " + PathFinder.getObjUniqueReferent(substance.get.getContainer().get, getCurrentAgentLocation(runner)).get + " to " + PathFinder.getObjUniqueReferent(boxNonconductive, getCurrentAgentLocation(runner)).get, runner)
      }
    }

    // Wait one moment
    runAction("wait1", runner)

    // Return
    return (true, getActionHistory(runner))
  }

/*
  def mkGoldActionSequencePowerComponentRenewable(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String]) = {
    val universe = runner.agentInterface.get.universe
    val agent = runner.agentInterface.get.agent

    // Task variables
    val partToPower = this.getTaskValueStr(modifiers, key = "componentToPower")
    val renewablePowerSource = this.getTaskValueStr(modifiers, key = "renewableSource")
    val nonrenewablePowerSource = this.getTaskValueStr(modifiers, key = "nonrenewableSource")
    val combinationNum = this.getTaskValueInt(modifiers, key = "variationIdx").get
    var powerSourceToUse:Option[String] = None
    var powerSourceDescription = ""

    // Hacky -- uses the variation number to determine whether the task will be choosing the renewable or non-renewable power source
    if (combinationNum % 2 == 0) {
      powerSourceDescription = "renewable"
      powerSourceToUse = renewablePowerSource
    } else {
      powerSourceDescription = "nonrenewable"
      powerSourceToUse = nonrenewablePowerSource
    }


    // Step 1: Move from starting location to workshop
    val partLocation = "workshop"
    val startLocation = agent.getContainer().get.name
    val (actions, actionStrs) = PathFinder.createActionSequence(universe, agent, startLocation, endLocation = partLocation)
    runActionSequence(actionStrs, runner)

    // Step 1A: Look around
    val (actionLook, actionLookStr) = PathFinder.actionLookAround(agent)
    runAction(actionLookStr, runner)

    // Step 1B: Look at part to power (TODO)


    // Step 2: Get references to parts
    val curLoc1 = PathFinder.getEnvObject(queryName = getCurrentAgentLocation(runner).name, universe)    // Get a pointer to the whole room the answer box is in
    val objsInRoom = curLoc1.get.getContainedObjectsRecursiveAccessible(includeHidden = false)

    // Part to power
    val component = PathFinder.getAllEnvObject(partToPower.get, curLoc1.get)(0)

    // Parts to use to power
    val powerSource = PathFinder.getAllEnvObject(queryName = powerSourceToUse.get, curLoc1.get)(0)   //##
    val wires = Random.shuffle( curLoc1.get.getContainedAccessibleObjectsOfType[Wire](includeHidden = false).toList )
    if (wires.size < 2) {
      // Fail
      return (false, getActionHistory(runner))
    }

    val wire1 = wires(0)
    val wire2 = wires(1)

    // Focus on part
    runAction("focus on " + PathFinder.getObjUniqueReferent(component, getCurrentAgentLocation(runner)).get, runner)

    // If renewable, the power source needs to be outside for wind/solar
    if (powerSourceDescription == "renewable") {
      // Pick up all parts
      runAction("pick up " + PathFinder.getObjUniqueReferent(component, getCurrentAgentLocation(runner)).get, runner)
      runAction("pick up " + PathFinder.getObjUniqueReferent(powerSource, getCurrentAgentLocation(runner)).get, runner)
      runAction("pick up " + PathFinder.getObjUniqueReferent(wire1, getCurrentAgentLocation(runner)).get, runner)
      runAction("pick up " + PathFinder.getObjUniqueReferent(wire2, getCurrentAgentLocation(runner)).get, runner)

      // Go outside
      val (actions1, actionStrs1) = PathFinder.createActionSequence(universe, agent, startLocation = agent.getContainer().get.name, endLocation = "outside")
      runActionSequence(actionStrs1, runner)

      // Drop all parts
      runAction("drop " + PathFinder.getObjUniqueReferent(component, getCurrentAgentLocation(runner)).get, runner)
      runAction("drop " + PathFinder.getObjUniqueReferent(powerSource, getCurrentAgentLocation(runner)).get, runner)
      runAction("drop " + PathFinder.getObjUniqueReferent(wire1, getCurrentAgentLocation(runner)).get, runner)
      runAction("drop " + PathFinder.getObjUniqueReferent(wire2, getCurrentAgentLocation(runner)).get, runner)
    }

    // Look around
    runAction("look around", runner)

    // Do actions
    // Connect battery to wires
    val powerSourceRef = powerSource.name //PathFinder.getObjUniqueReferent(powerSource, getCurrentAgentLocation(runner)).get   //## TODO: Not clear why the referent ('generator') is not resolving here.
    runAction("connect " + powerSourceRef + " anode to " + PathFinder.getObjUniqueReferent(wire1, getCurrentAgentLocation(runner)).get + " terminal 1", runner)
    runAction("connect " + powerSourceRef + " cathode to " + PathFinder.getObjUniqueReferent(wire2, getCurrentAgentLocation(runner)).get + " terminal 1", runner)

    // Connect wires to component
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
    runAction("connect " + PathFinder.getObjUniqueReferent(wire2, getCurrentAgentLocation(runner)).get + " terminal 2 to " + anodeReferent, runner)   // to device anode

    // If power source is non-renewable, we need to turn it on
    if (powerSourceDescription == "nonrenewable") {
      runAction("activate " + powerSourceRef, runner)
    }

    // Wait one moment, for the power to cycle
    runAction("wait1", runner)
    runAction("wait1", runner)

    // Look around
    runAction(actionLookStr, runner)


    // Return
    return (true, getActionHistory(runner))
  }
*/

}


object TaskElectricalConductivity {
  val MODE_TEST_CONDUCTIVITY            = "test conductivity"

  def registerTasks(taskMaker:TaskMaker1): Unit = {
    taskMaker.addTask( new TaskElectricalConductivity(mode = MODE_TEST_CONDUCTIVITY) )
  }

}
