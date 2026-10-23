package scienceworld.tasks.specifictasks

import scienceworld.actions.Action
import scienceworld.goldagent.PathFinder
import scienceworld.objects.agent.Agent
import scienceworld.objects.containers.{CeramicCup, FlowerPot}
import scienceworld.objects.electricalcomponent.{Battery, ElectricBuzzer, ElectricMotor, GasGenerator, LightBulb, NuclearGenerator, PolarizedElectricalComponent, SolarPanel, UnpolarizedElectricalComponent, WindGenerator, Wire}
import scienceworld.objects.livingthing.animals.Animal
import scienceworld.objects.livingthing.plant.{Plant, Soil}
import scienceworld.objects.taskitems.AnswerBox
import scienceworld.processes.PlantReproduction
import scienceworld.runtime.pythonapi.PythonInterface
import scienceworld.struct.EnvObject
import scienceworld.tasks.{Task, TaskMaker1, TaskModifier, TaskObject, TaskValueInt, TaskValueStr}
import scienceworld.tasks.goals.{Goal, GoalSequence}
import scienceworld.tasks.goals.specificgoals.{GoalActivateDevice, GoalElectricallyConnected, GoalFind, GoalInRoomWithObject, GoalLifeStage, GoalMoveToNewLocation, GoalObjectConnectedToWire, GoalWireConnectsObjectAndAnyPowerSource}
import scienceworld.tasks.specifictasks.TaskElectricCircuit.{MODE_POWER_COMPONENT, MODE_POWER_COMPONENT_RENEWABLE}

import scala.collection.mutable.ArrayBuffer
import scala.util.Random
import scala.util.control.Breaks.{break, breakable}


class TaskElectricCircuit(val mode:String = MODE_POWER_COMPONENT) extends TaskParametric {
  val taskName = mode.replaceAll(" ", "-").replaceAll("[()]", "")

  val locations = Array("workshop")

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

    // Generate array of lights
    val components = new ArrayBuffer[TaskObject]
    for (color <- lightColors) {
      val lightbulb = new LightBulb(color)
      components.append( new TaskObject(lightbulb.name, Some(lightbulb), roomToGenerateIn = location, Array.empty[String], generateNear = 0) )
    }
    // Additional parts (motor)
    val electricMotor = new ElectricMotor()
    components.append(new TaskObject(electricMotor.name, Some(electricMotor), roomToGenerateIn = location, Array.empty[String], generateNear = 0))
    // Additional parts (buzzer)
    val electricBuzzer = new ElectricBuzzer()
    components.append(new TaskObject(electricBuzzer.name, Some(electricBuzzer), roomToGenerateIn = location, Array.empty[String], generateNear = 0))

    // Iterate through all possible components to power
    for (component <- components) {
      partToPower.append(components.toArray ++ Array( new TaskValueStr(key = "componentToPower", value = component.name) ))
    }
  }

  // Variation 3: Renewable power source
  val renewablePowerSource = new ArrayBuffer[ Array[TaskModifier] ]()

  for (location <- locations) {
    // Solar panel
    val solarPanel = new SolarPanel()
    renewablePowerSource.append( Array(
      new TaskObject(solarPanel.name, Some(solarPanel), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
      new TaskValueStr(key = "renewableSource", value = solarPanel.name)
    ))

    // Wind generator
    val windGenerator = new WindGenerator()
    renewablePowerSource.append( Array(
      new TaskObject(windGenerator.name, Some(windGenerator), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
      new TaskValueStr(key = "renewableSource", value = windGenerator.name)
    ))
  }

  // Variation 4: Non-renewable power source
  val nonrenewablePowerSource = new ArrayBuffer[ Array[TaskModifier] ]()
  for (location <- locations) {
    // Gas generator
    val gasGenerator = new GasGenerator()
    nonrenewablePowerSource.append( Array(
      new TaskObject(gasGenerator.name, Some(gasGenerator), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
      new TaskValueStr(key = "nonrenewableSource", value = gasGenerator.name)
    ))

    // Nuclear generator
    val nuclearGenerator = new NuclearGenerator()
    nonrenewablePowerSource.append( Array(
      new TaskObject(nuclearGenerator.name, Some(nuclearGenerator), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
      new TaskValueStr(key = "nonrenewableSource", value = nuclearGenerator.name)
    ))
  }


  // Combinations
  val combinations = for {
    i <- powerSource
    j <- partToPower
    k <- renewablePowerSource
    m <- nonrenewablePowerSource
  } yield List(i, j, k, m)

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
    val partToPower = this.getTaskValueStr(modifiers, key = "componentToPower")
    if (partToPower.isEmpty) throw new RuntimeException("ERROR: Unable to initialize task (componentToPower is undefined).")


    var subTask = ""
    val gSequence = new ArrayBuffer[Goal]
    val gSequenceUnordered = new ArrayBuffer[Goal]
    var description:String = "<empty>"
    if (mode == MODE_POWER_COMPONENT) {
      gSequence.append(new GoalFind(objectName = partToPower.get, failIfWrong = true, description = "focus on task object"))
      gSequence.append(new GoalActivateDevice(deviceName = partToPower.get, description = "power task object"))

      // Unordered
      gSequenceUnordered.append(new GoalMoveToNewLocation(_isOptional = true, unlessInLocation = "", description = "move to a new location") )            // Move to any new location
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = partToPower.get, _isOptional = true, description = "be in same location as part to power"))

      // Connect the component to a wire on either side
      gSequenceUnordered.append(new GoalObjectConnectedToWire(partToPower.get, terminal1 = true, terminal2 = false, anode = true, cathode = false, description = "Connect the task object's (terminal1/anode) to a wire"))
      gSequenceUnordered.append(new GoalObjectConnectedToWire(partToPower.get, terminal1 = false, terminal2 = true, anode = false, cathode = true, description = "Connect the task object's (terminal2/cathode) to a wire"))

      // Connect a wire between at least one side of the component, and one side of a power source (e.g. battery)
      gSequenceUnordered.append(new GoalWireConnectsObjectAndAnyPowerSource(partToPower.get, description = "Task object is at least partially connected to power source through wire"))


      description = "Your task is to turn on the " + partToPower.get + ". First, focus on the " + partToPower.get + ". Then, create an electrical circuit that powers it on. "

    } else if (mode == MODE_POWER_COMPONENT_RENEWABLE) {
      // Randomly pick whether the user should use the renewable or non-renewable power source, based on the combination #
      val renewablePowerSource = this.getTaskValueStr(modifiers, key = "renewableSource")
      val nonrenewablePowerSource = this.getTaskValueStr(modifiers, key = "nonrenewableSource")
      var powerSourceToUse:Option[String] = None
      var powerSourceDescription = ""
      if (combinationNum % 2 == 0) {
        powerSourceDescription = "renewable"
        powerSourceToUse = renewablePowerSource
      } else {
        powerSourceDescription = "nonrenewable"
        powerSourceToUse = nonrenewablePowerSource
      }

      gSequence.append(new GoalFind(objectName = partToPower.get, failIfWrong = true, description = "focus on task object"))
      gSequence.append(new GoalActivateDevice(deviceName = partToPower.get, description = "power task object"))
      gSequence.append(new GoalElectricallyConnected(connectedPartName = powerSourceToUse.get, failIfWrong = true, description = "use correct power source"))

      // Unordered
      gSequenceUnordered.append(new GoalMoveToNewLocation(_isOptional = true, unlessInLocation = "", description = "move to a new location") )            // Move to any new location
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = partToPower.get, _isOptional = true, description = "be in same location as part to power"))

      // Connect the component to a wire on either side
      gSequenceUnordered.append(new GoalObjectConnectedToWire(partToPower.get, terminal1 = true, terminal2 = false, anode = true, cathode = false, description = "connect the task object's (terminal1/anode) to a wire"))
      gSequenceUnordered.append(new GoalObjectConnectedToWire(partToPower.get, terminal1 = false, terminal2 = true, anode = false, cathode = true, description = "connect the task object's (terminal2/cathode) to a wire"))

      // Connect a wire between at least one side of the component, and one side of the correct power source (e.g. solar panel)
      gSequenceUnordered.append(new GoalWireConnectsObjectAndAnyPowerSource(partToPower.get, powerSourceName = powerSourceToUse.get, description = "task object is at least partially connected to power source through wire"))


      // TODO: Add goal condition that checks that the appropriate power source was used
      description = "Your task is to turn on the " + partToPower.get + " by powering it using a " + powerSourceDescription + " power source. First, focus on the " + partToPower.get + ". Then, create an electrical circuit that powers it on. "

    } else {
      throw new RuntimeException("ERROR: Unrecognized task mode: " + mode)
    }

    val taskLabel = taskName + "-variation" + combinationNum
    //val description = "Your task is to find a " + subTask + ". First, focus on the thing. Then, move it to the " + answerBoxName + " in the " + answerBoxLocation + "."
    val goalSequence = new GoalSequence(gSequence.toArray, gSequenceUnordered.toArray)

    val newModifiers = modifiers ++ Array[TaskModifier](new TaskValueInt(key = "variationIdx", value = combinationNum))
    val task = new Task(taskName, description, goalSequence, taskModifiers = newModifiers)

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
    if (mode == MODE_POWER_COMPONENT) {
      return mkGoldActionSequencePowerComponent(modifiers, runner)
    } else if (mode == MODE_POWER_COMPONENT_RENEWABLE) {
      return mkGoldActionSequencePowerComponentRenewable(modifiers, runner)
    } else {
      throw new RuntimeException("ERROR: Unrecognized task mode: " + mode)
    }

  }

  /*
   * Gold action sequences
   */
  def mkGoldActionSequencePowerComponent(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String]) = {
    val universe = runner.agentInterface.get.universe
    val agent = runner.agentInterface.get.agent

    // Task variables
    val partToPower = this.getTaskValueStr(modifiers, key = "componentToPower")

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
    val battery = curLoc1.get.getContainedAccessibleObjectsOfType[Battery](includeHidden = false)
    val wires = Random.shuffle( curLoc1.get.getContainedAccessibleObjectsOfType[Wire](includeHidden = false).toList.sortBy(_.uuid) )
    if (wires.size < 2) {
      // Fail
      return (false, getActionHistory(runner))
    }

    val wire1 = wires(0)
    val wire2 = wires(1)

    // Focus on part
    runAction("focus on " + PathFinder.getObjUniqueReferent(component, getCurrentAgentLocation(runner)).get, runner)

    // Do actions
    // Connect battery to wires
    runAction("connect battery anode to " + PathFinder.getObjUniqueReferent(wire1, getCurrentAgentLocation(runner)).get + " terminal 1", runner)
    runAction("connect battery cathode to " + PathFinder.getObjUniqueReferent(wire2, getCurrentAgentLocation(runner)).get + " terminal 1", runner)

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


    // Wait one moment, for the power to cycle
    runAction("wait1", runner)
    runAction("wait1", runner)

    // Look around
    runAction(actionLookStr, runner)


    // Return
    return (true, getActionHistory(runner))
  }


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
    val wires = Random.shuffle( curLoc1.get.getContainedAccessibleObjectsOfType[Wire](includeHidden = false).toList.sortBy(_.uuid) )
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

  /*
    def mkGoldActionSequencePowerComponent(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String]) = {
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

   */

}


object TaskElectricCircuit {
  val MODE_POWER_COMPONENT              = "power component"
  val MODE_POWER_COMPONENT_RENEWABLE    = "power component (renewable vs nonrenewable energy)"

  def registerTasks(taskMaker:TaskMaker1): Unit = {
    taskMaker.addTask( new TaskElectricCircuit(mode = MODE_POWER_COMPONENT) )
    taskMaker.addTask( new TaskElectricCircuit(mode = MODE_POWER_COMPONENT_RENEWABLE) )
  }

}
