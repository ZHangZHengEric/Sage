package scienceworld.tasks.specifictasks

import scienceworld.objects.agent.Agent
import scienceworld.objects.devices.StopWatch
import scienceworld.objects.misc.InclinedPlane
import scienceworld.objects.substance.{Brick, SteelBlock, WoodBlock}
import scienceworld.properties.{AluminumProp, BrassProp, BronzeProp, CaesiumProp, CeramicProp, ChocolateProp, CopperProp, CottonClothProp, GlassProp, GreenPaintProp, IronProp, LeadProp, PaperProp, PlasticProp, PlatinumProp, RubberProp, SandpaperProp, SoapyWaterProp, SteelProp, TinProp, TitaniumProp, UnknownFrictionMaterialA, UnknownFrictionMaterialB, UnknownFrictionMaterialC, UnknownFrictionMaterialD, UnknownFrictionMaterialE, UnknownFrictionMaterialF, UnknownFrictionMaterialG, UnknownFrictionMaterialH, UnknownFrictionMaterialJ, WoodProp, ZincProp}
import scienceworld.struct.EnvObject
import scienceworld.tasks.{Task, TaskMaker1, TaskModifier, TaskObject, TaskValueStr}
import scienceworld.tasks.goals.{Goal, GoalSequence}
import scienceworld.tasks.goals.specificgoals.{GoalActivateDeviceWithName, GoalDeactivateDeviceWithName, GoalFindInclinedPlane, GoalMoveToLocation, GoalMoveToNewLocation, GoalPastActionExamineObject, GoalSpecificObjectInDirectContainer}
import TaskInclinedPlane2._
import scienceworld.actions.Action
import scienceworld.goldagent.PathFinder
import scienceworld.runtime.pythonapi.PythonInterface
import scienceworld.tasks.specifictasks.TaskInclinedPlane1.actionSequenceMeasureBlockFallTime

import scala.collection.mutable.ArrayBuffer
import scala.util.Random
import scala.util.control.Breaks.{break, breakable}


class TaskInclinedPlane2(val mode:String = MODE_FRICTION_UNNAMED) extends TaskParametric {
  val taskName = mode.replaceAll(" ", "-").replaceAll("[()]", "")

  val locations = Array("workshop")

  // Variation 1 + 2: Inclined planes of various material surfaces (and frictions)
  val inclinedPlanes1 = new ArrayBuffer[ Array[TaskModifier] ]()
  val inclinedPlanes2 = new ArrayBuffer[ Array[TaskModifier] ]()
  for (location <- locations) {

    // Make a set of inclined plane objects of various surfaces
    val inclinedPlaneObjects1 = TaskInclinedPlane2.mkInclinedPlaneSet(angleDeg = 45.0)
    for (inclinedPlane <- inclinedPlaneObjects1) {
      inclinedPlanes1.append( Array(new TaskObject(inclinedPlane.name, Some(inclinedPlane), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
        new TaskValueStr(key = "planeLocation", value = location) ) )
    }

    val inclinedPlaneObjects2 = TaskInclinedPlane2.mkInclinedPlaneSet(angleDeg = 45.0)
    for (inclinedPlane <- inclinedPlaneObjects2) {
      inclinedPlanes2.append( Array(new TaskObject(inclinedPlane.name, Some(inclinedPlane), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true)) )
    }

  }

  // Variation 3: Masses to roll down ramp
  val masses = new ArrayBuffer[ Array[TaskModifier] ]()
  for (location <- locations) {
    val block1 = new WoodBlock()
    masses.append( Array(new TaskObject(block1.name, Some(block1), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
                          new TaskValueStr(key = "blockName", value = block1.name) ))

    val block2 = new SteelBlock()
    masses.append( Array(new TaskObject(block2.name, Some(block2), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
                          new TaskValueStr(key = "blockName", value = block2.name) ))

    val brick = new Brick()
    masses.append( Array(new TaskObject(brick.name, Some(brick), roomToGenerateIn = location, Array.empty[String], generateNear = 0, forceAdd = true),
                          new TaskValueStr(key = "blockName", value = brick.name) ))
  }

  // Variation 4: Time measurement device
  val timeMeasurementDevice = new ArrayBuffer[ Array[TaskModifier] ]()
  for (location <- locations) {
    val stopwatch = new StopWatch()
    timeMeasurementDevice.append( Array(new TaskObject(stopwatch.name, Some(stopwatch), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
                                        new TaskValueStr(key = "timeDeviceName", value = stopwatch.name),
                                        new TaskValueStr(key = "timeLocation", value = location) ))
  }


  // Combinations
  var combinations1 = for {
    i <- inclinedPlanes1
    j <- inclinedPlanes2
    k <- masses
    m <- timeMeasurementDevice
  } yield List(i, j, k, m)

  // Remove any combinations that have the same coefficient of friction
  // Also add extra information as keys (e.g. most friction/least friction)
  val combinations = TaskInclinedPlane2.filterDuplicatesAndAddMostLeast(combinations1)

  // Randomize order, and subsample to half the original size (so some combinations are never seen)
  //val r = new scala.util.Random(2)
  //combinations = r.shuffle(combinations.toList).slice(0, combinations.length/10).toArray


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
    val leastFriction = this.getTaskValueStr(modifiers, "leastFriction")
    if (leastFriction.isEmpty) throw new RuntimeException("ERROR: Failed to find name of inclined plane with least friction.")
    val mostFriction = this.getTaskValueStr(modifiers, "mostFriction")
    if (mostFriction.isEmpty) throw new RuntimeException("ERROR: Failed to find name of inclined plane with most friction.")
    val modeMostLeastFriction = this.getTaskValueStr(modifiers, "mode")
    if (modeMostLeastFriction.isEmpty) throw new RuntimeException("ERROR: Failed to find inclined plane friction task mode. ")

    val planeName1 = this.getTaskValueStr(modifiers, "planeName1")
    val planeName2 = this.getTaskValueStr(modifiers, "planeName2")
    val planeLocation = this.getTaskValueStr(modifiers, "planeLocation")
    val blockName = this.getTaskValueStr(modifiers, "blockName")
    val timeDeviceName = this.getTaskValueStr(modifiers, key = "timeDeviceName")


    val gSequence = new ArrayBuffer[Goal]
    val gSequenceUnordered = new ArrayBuffer[Goal]
    var description:String = "<empty>"
    if (mode == MODE_FRICTION_UNNAMED) {

      if (modeMostLeastFriction.get == "most") {
        // Most friction
        gSequence.append(new GoalFindInclinedPlane(surfaceName = mostFriction.get, failIfWrong = true, _defocusOnSuccess = true))
      } else {
        // Least friction
        gSequence.append(new GoalFindInclinedPlane(surfaceName = leastFriction.get, failIfWrong = true, _defocusOnSuccess = true))
      }

      gSequenceUnordered.append( new GoalMoveToNewLocation(_isOptional = true, unlessInLocation = planeLocation.get, description = "move to a new location (unless starting in task location)") )            // Move to any new location
      gSequenceUnordered.append( new GoalMoveToLocation(planeLocation.get, _isOptional = true, description = "move to the location asked by the task") )

      gSequenceUnordered.append( new GoalSpecificObjectInDirectContainer(containerName = planeName1.get, validObjectNames = Array(blockName.get), description = "move block to plane 1", key = "b1") )
      gSequenceUnordered.append( new GoalActivateDeviceWithName(deviceName = timeDeviceName.get, description = "activate time keeping device", key = "aTime1", keysMustBeCompletedBefore = Array("b1")) )
      gSequenceUnordered.append( new GoalDeactivateDeviceWithName(deviceName = timeDeviceName.get, description = "deactivate time keeping device", key = "dTime1", keysMustBeCompletedBefore = Array("aTime1")) )
      gSequenceUnordered.append( new GoalPastActionExamineObject(objectName = timeDeviceName.get, description = "read time keeping device", key = "readTime1", keysMustBeCompletedBefore = Array("dTime1") ))

      gSequenceUnordered.append( new GoalSpecificObjectInDirectContainer(containerName = planeName2.get, validObjectNames = Array(blockName.get), description = "move block to plane 2", key = "b2") )
      gSequenceUnordered.append( new GoalActivateDeviceWithName(deviceName = timeDeviceName.get, description = "activate time keeping device", key = "aTime2", keysMustBeCompletedBefore = Array("b2")) )
      gSequenceUnordered.append( new GoalDeactivateDeviceWithName(deviceName = timeDeviceName.get, description = "deactivate time keeping device", key = "dTime2", keysMustBeCompletedBefore = Array("aTime2")) )
      gSequenceUnordered.append( new GoalPastActionExamineObject(objectName = timeDeviceName.get, description = "read time keeping device", key = "readTime2", keysMustBeCompletedBefore = Array("dTime2") ))


      val planeNames = Random.shuffle( List(leastFriction.get, mostFriction.get) )
      description = "Your task is to determine which of the two inclined planes (" + planeNames.mkString(", ") + ") has the " + modeMostLeastFriction.get + " friction. After completing your experiment, focus on the inclined plane with the " + modeMostLeastFriction.get + " friction."


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
    if (mode == MODE_FRICTION_UNNAMED) {
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
    // Step 1: Find seed type
    val leastFriction = this.getTaskValueStr(modifiers, "leastFriction").get
    val mostFriction = this.getTaskValueStr(modifiers, "mostFriction").get
    val modeMostLeastFriction = this.getTaskValueStr(modifiers, "mode").get

    val planeName1 = this.getTaskValueStr(modifiers, "planeName1").get
    val planeName2 = this.getTaskValueStr(modifiers, "planeName2").get
    val planeLocation = this.getTaskValueStr(modifiers, "planeLocation").get
    val blockName = this.getTaskValueStr(modifiers, "blockName").get
    val timeDeviceName = this.getTaskValueStr(modifiers, key = "timeDeviceName").get


    // Step 1: Move from starting location to task location
    val startLocation = agent.getContainer().get.name
    val (actions, actionStrs) = PathFinder.createActionSequence(universe, agent, startLocation, endLocation = planeLocation)
    runActionSequence(actionStrs, runner)

    // Look around
    runAction("look around", runner)

    // Take stop watch
    val timeTools = PathFinder.getAllAccessibleEnvObject(queryName = timeDeviceName, getCurrentAgentLocation(runner))
    if (timeTools.length == 0) return (false, getActionHistory(runner))
    val timeTool = timeTools(0)
    runAction("pick up " + PathFinder.getObjUniqueReferent(timeTool, getCurrentAgentLocation(runner)).get, runner)


    // Get reference to block
    val blocks = PathFinder.getAllAccessibleEnvObject(queryName = blockName, getCurrentAgentLocation(runner))
    if (blocks.length == 0) return (false, getActionHistory(runner))
    val block = blocks(0)

    // Get reference to inclined planes
    val inclinedPlanes = getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[InclinedPlane]().toArray.sortBy(obj => (obj.name, obj.uuid))
    val inclinedPlane1 = inclinedPlanes(0)
    val inclinedPlane2 = inclinedPlanes(1)


    // Slide block down plane 1
    val (success1, time1) = actionSequenceMeasureBlockFallTime(block = block, timeTool = timeTool, inclinedPlane = inclinedPlane1, runner)
    if (!success1) return (false, getActionHistory(runner))

    // Slide block down plane 2
    val (success2, time2) = actionSequenceMeasureBlockFallTime(block = block, timeTool = timeTool, inclinedPlane = inclinedPlane2, runner)
    if (!success2) return (false, getActionHistory(runner))


    var planeToSelect:Option[EnvObject] = None
    if (time1 > time2) {
      // Plane 1 had more friction
      if (modeMostLeastFriction == "most") {
        planeToSelect = Some(inclinedPlane1)
      } else {
        planeToSelect = Some(inclinedPlane2)
      }
    } else {
      // Plane 2 had more friction
      if (modeMostLeastFriction == "most") {
        planeToSelect = Some(inclinedPlane2)
      } else {
        planeToSelect = Some(inclinedPlane1)
      }
    }

    // Step 2: Focus on substance
    runAction("focus on " + PathFinder.getObjUniqueReferent(planeToSelect.get, getCurrentAgentLocation(runner)).get, runner)

    // Wait one moment
    runAction("wait1", runner)

    // Return
    return (true, getActionHistory(runner))
  }


}


object TaskInclinedPlane2 {
  val MODE_FRICTION_UNNAMED       = "inclined plane friction (unnamed surfaces)"

  def registerTasks(taskMaker:TaskMaker1): Unit = {
    taskMaker.addTask( new TaskInclinedPlane2(mode = MODE_FRICTION_UNNAMED) )
  }


  /*
   * Helper functions
   */

  // Make a set of inclined planes
  def mkInclinedPlaneSet(angleDeg:Double = 45.0):Array[EnvObject] = {
    val out = new ArrayBuffer[EnvObject]

    // Metal surfaces
    //out.append( new InclinedPlane(angleDeg, surfaceMaterial = new UnknownFrictionMaterialA) )
    out.append( new InclinedPlane(angleDeg, surfaceMaterial = new UnknownFrictionMaterialB) )
    out.append( new InclinedPlane(angleDeg, surfaceMaterial = new UnknownFrictionMaterialC) )
    out.append( new InclinedPlane(angleDeg, surfaceMaterial = new UnknownFrictionMaterialD) )
    out.append( new InclinedPlane(angleDeg, surfaceMaterial = new UnknownFrictionMaterialE) )
    out.append( new InclinedPlane(angleDeg, surfaceMaterial = new UnknownFrictionMaterialF) )
    out.append( new InclinedPlane(angleDeg, surfaceMaterial = new UnknownFrictionMaterialG) )
    out.append( new InclinedPlane(angleDeg, surfaceMaterial = new UnknownFrictionMaterialH) )
    out.append( new InclinedPlane(angleDeg, surfaceMaterial = new UnknownFrictionMaterialJ) )

    // Randomize Order
    val r = new scala.util.Random(4)
    return r.shuffle(out).toArray
  }


  def filterDuplicatesAndAddMostLeast(in:Traversable[List[Array[TaskModifier]]], threshold:Double = 0.05): Array[List[List[TaskModifier]]] = {
    val out = new ArrayBuffer[ List[List[TaskModifier]] ]

    var count:Int = 0

    for (tmSet <- in) {
      val allModifiers = tmSet.flatten
      // Find all inclined planes
      val inclinedPlanes = new ArrayBuffer[InclinedPlane]
      for (modifier <- allModifiers) {
        modifier match {
          case m:TaskObject => {
            if (m.exampleInstance.isDefined) {
              m.exampleInstance.get match {
                case plane: InclinedPlane => {
                  inclinedPlanes.append(plane)
                }
                case _ => {
                  // Do nothing
                }
              }
            }
          }
          case _ => {
            // Do nothing
          }
        }
      }

      breakable {
        var leastFriction:Double = 1.0
        var leastFrictionName:String = "DEFAULT"
        var mostFriction:Double = 0.0
        var mostFrictionName:String = "DEFAULT"

        for (i <- 0 until inclinedPlanes.length) {
          val plane1 = inclinedPlanes(i)

          for (j <- 0 until inclinedPlanes.length) {
            val plane2 = inclinedPlanes(j)

            if (i != j) {
              // Check to see if the friction coefficients of the two materials are too similar (i.e. within 'threshold').  If they are, don't keep them in the list.
              val delta = math.abs(plane1.surfaceMaterial.frictionCoefficient - plane2.surfaceMaterial.frictionCoefficient)
              if (delta <= threshold) break
            }
          }

          if (plane1.surfaceMaterial.frictionCoefficient < leastFriction) {
            leastFriction = plane1.surfaceMaterial.frictionCoefficient
            leastFrictionName = plane1.surfaceMaterial.substanceName
          }
          if (plane1.surfaceMaterial.frictionCoefficient > mostFriction) {
            mostFriction = plane1.surfaceMaterial.frictionCoefficient
            mostFrictionName = plane1.surfaceMaterial.substanceName
          }

        }

        // If we reach here, the list is okay (i.e. no duplicates/near duplicates).  Store it.

        // First, pick whether the agent should find the inclined plane with the most or least friction
        var modifierModeKey = new TaskValueStr(key = "mode", value = "least")
        if (count % 2 == 0) {
          modifierModeKey = new TaskValueStr(key = "mode", value = "most")
        }
        count += 1

        // Then, assemble the task modifiers
        val taskModifiers = allModifiers ++
          Array(new TaskValueStr(key = "leastFriction", leastFrictionName), new TaskValueStr(key = "mostFriction", mostFrictionName)) ++
          Array(new TaskValueStr(key = "planeName1", inclinedPlanes(0).getDescriptName()), new TaskValueStr(key = "planeName2", inclinedPlanes(1).getDescriptName())) ++
          Array(modifierModeKey)


        out.append( List(taskModifiers.toList) )      // Wrapped in an extra List() to match how this appears in other Tasks
      }

    }

    // Return
    out.toArray
  }

}
