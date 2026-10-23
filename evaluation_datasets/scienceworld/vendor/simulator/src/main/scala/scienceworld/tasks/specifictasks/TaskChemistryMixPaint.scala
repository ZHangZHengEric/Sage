package scienceworld.tasks.specifictasks

import scienceworld.actions.Action
import scienceworld.goldagent.PathFinder
import scienceworld.objects.agent.Agent
import scienceworld.objects.containers.{Container, GlassCup, Jug, TinCup, WoodBowl, WoodCup}
import scienceworld.objects.containers.furniture.{Closet, Cupboard, Desk}
import scienceworld.objects.electricalcomponent.{Battery, PolarizedElectricalComponent, UnpolarizedElectricalComponent, Wire}
import scienceworld.objects.substance.paint.{BluePaint, Paint, RedPaint, YellowPaint}
import scienceworld.objects.substance.{Soap, SodiumChloride}
import scienceworld.runtime.pythonapi.PythonInterface
import scienceworld.struct.EnvObject
import scienceworld.tasks.{Task, TaskMaker1, TaskModifier, TaskObject, TaskValueStr}
import scienceworld.tasks.goals.{Goal, GoalSequence}
import scienceworld.tasks.goals.specificgoals.{GoalFind, GoalInRoomWithObject, GoalMoveToLocation, GoalMoveToNewLocation, GoalObjectsInSingleContainer}
import scienceworld.tasks.specifictasks.TaskChemistryMixPaint._

import scala.collection.mutable.ArrayBuffer
import scala.util.Random
import scala.util.control.Breaks.{break, breakable}


class TaskChemistryMixPaint(val mode:String = MODE_CHEMISTRY_MIX_PAINT_SECONDARY) extends TaskParametric {
  val taskName = mode.replaceAll(" ", "-").replaceAll("[()]", "")


  // Variation 1: Which seeds to grow
  val additionalPaint = new ArrayBuffer[ Array[TaskModifier] ]()
  val mixingContainers = Random.shuffle( List(new GlassCup(), new WoodBowl(), new Jug()) )
  val locations = Array("art studio", "workshop")

  //val locations = Array("greenhouse")
  for (location <- locations) {
    val paints2 = Array(new RedPaint, new BluePaint, new YellowPaint) //, new GreenPaint, new VioletPaint, new OrangePaint)

    // Add an extra cupboard full of paint in some location
    val cupboard = new Cupboard()
    for (paint <- paints2) {
      val woodcup = new WoodCup()
      woodcup.addObject(paint)
      cupboard.addObject(woodcup)
    }
    cupboard.name = "paint cupboard"

    additionalPaint.append( Array(
      new TaskObject(cupboard.name, Some(cupboard), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
      new TaskValueStr(key = "location", value = location)
    ))

    if (location != "art studio") {
      // Add a mixing container to any locations that aren't the art studio
      additionalPaint(additionalPaint.size-1) = additionalPaint(additionalPaint.size-1) ++ Array( new TaskObject(mixingContainers(0).name, Some(mixingContainers(0)), roomToGenerateIn = location, Array.empty[String], generateNear = 0 ))
    }

    // Add an extra closet full of paint in some location
    val closet = new Closet()
    for (paint <- paints2) {
      val glasscup = new GlassCup()
      glasscup.addObject(paint)
      closet.addObject(glasscup)
    }
    closet.name = "paint closet"

    additionalPaint.append( Array(
      new TaskObject(closet.name, Some(closet), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
      new TaskValueStr(key = "location", value = location)
    ))

    if (location != "art studio") {
      // Add a mixing container to any locations that aren't the art studio
      additionalPaint(additionalPaint.size-1) = additionalPaint(additionalPaint.size-1) ++ Array( new TaskObject(mixingContainers(1).name, Some(mixingContainers(1)), roomToGenerateIn = location, Array.empty[String], generateNear = 0 ))
    }


    // Add an extra cupboard full of paint in some location
    val desk = new Desk()
    for (paint <- paints2) {
      val tincup = new TinCup()
      tincup.addObject(paint)
      desk.addObject(tincup)
    }

    additionalPaint.append( Array(
      new TaskObject(desk.name, Some(desk), roomToGenerateIn = location, Array.empty[String], generateNear = 0),
      new TaskValueStr(key = "location", value = location)
    ))

    if (location != "art studio") {
      // Add a mixing container to any locations that aren't the art studio
      additionalPaint(additionalPaint.size-1) = additionalPaint(additionalPaint.size-1) ++ Array( new TaskObject(mixingContainers(2).name, Some(mixingContainers(2)), roomToGenerateIn = location, Array.empty[String], generateNear = 0 ))
    }


  }


  // Variation 2: Which paint to manufacture
  val paintNames = new ArrayBuffer[ Array[TaskModifier] ]()

  // Green
  paintNames.append(Array(
    new TaskValueStr(key = "inputChemicalsSecondary", value = "blue paint,yellow paint"),
    new TaskValueStr(key = "inputChemicalsTertiary", value = "green paint,blue paint"),
    new TaskValueStr(key = "secondaryColor", value = "green paint"),
    new TaskValueStr(key = "tertiaryColor", value = "green-blue paint")
  ))

  paintNames.append(Array(
    new TaskValueStr(key = "inputChemicalsSecondary", value = "blue paint,yellow paint"),
    new TaskValueStr(key = "inputChemicalsTertiary", value = "green paint,yellow paint"),
    new TaskValueStr(key = "secondaryColor", value = "green paint"),
    new TaskValueStr(key = "tertiaryColor", value = "yellow-green paint")
  ))

  // Orange
  paintNames.append(Array(
    new TaskValueStr(key = "inputChemicalsSecondary", value = "red paint,yellow paint"),
    new TaskValueStr(key = "inputChemicalsTertiary", value = "orange paint,red paint"),
    new TaskValueStr(key = "secondaryColor", value = "orange paint"),
    new TaskValueStr(key = "tertiaryColor", value = "red-orange paint")
  ))

  paintNames.append(Array(
    new TaskValueStr(key = "inputChemicalsSecondary", value = "red paint,yellow paint"),
    new TaskValueStr(key = "inputChemicalsTertiary", value = "orange paint,yellow paint"),
    new TaskValueStr(key = "secondaryColor", value = "orange paint"),
    new TaskValueStr(key = "tertiaryColor", value = "yellow-orange paint")
  ))

  // Violet
  paintNames.append(Array(
    new TaskValueStr(key = "inputChemicalsSecondary", value = "red paint,blue paint"),
    new TaskValueStr(key = "inputChemicalsTertiary", value = "violet paint,red paint"),
    new TaskValueStr(key = "secondaryColor", value = "violet paint"),
    new TaskValueStr(key = "tertiaryColor", value = "violet-red paint")
  ))

  paintNames.append(Array(
    new TaskValueStr(key = "inputChemicalsSecondary", value = "red paint,blue paint"),
    new TaskValueStr(key = "inputChemicalsTertiary", value = "violet paint,blue paint"),
    new TaskValueStr(key = "secondaryColor", value = "violet paint"),
    new TaskValueStr(key = "tertiaryColor", value = "blue-violet paint")
  ))

  val paintNamesSorted = paintNames.sortBy(e => getTaskValueStr(e, "secondaryColor").get + " " + getTaskValueStr(e, "tertiaryColor").get  )

  // Combinations
  val combinations = for {
    i <- paintNames
    j <- additionalPaint
  } yield List(i, j)

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
    val secondaryColor = this.getTaskValueStr(modifiers, "secondaryColor")
    if (secondaryColor.isEmpty) throw new RuntimeException("ERROR: Failed to find secondary color in task setup.")
    val tertiaryColor = this.getTaskValueStr(modifiers, "tertiaryColor")
    if (tertiaryColor.isEmpty) throw new RuntimeException("ERROR: Failed to find tertiary color in task setup.")
    val inputColorsSecondary = this.getTaskValueStr(modifiers, "inputChemicalsSecondary").get.split(",")
    val inputColorsTertiary = this.getTaskValueStr(modifiers, "inputChemicalsTertiary").get.split(",")

    val paintLocation = this.getTaskValueStr(modifiers, "location")

    var subTask = ""
    val gSequence = new ArrayBuffer[Goal]
    val gSequenceUnordered = new ArrayBuffer[Goal]

    var description:String = "<empty>"
    if (mode == MODE_CHEMISTRY_MIX_PAINT_SECONDARY) {

      gSequence.append(new GoalFind(objectName = secondaryColor.get, failIfWrong = true, description = "focus on the mixing result (" + secondaryColor.get + ")"))

      gSequenceUnordered.append(new GoalMoveToNewLocation(_isOptional = true, unlessInLocation = "", description = "move to a new location") )            // Move to any new location

      for (inputChemical <- inputColorsSecondary) {
        gSequenceUnordered.append(new GoalInRoomWithObject(objectName = inputChemical, _isOptional = true, description = "be in same location as " + inputChemical))
      }
      gSequenceUnordered.append(new GoalObjectsInSingleContainer(objectNames = inputColorsSecondary, _isOptional = true, description = "have all ingredients alone in a single container"))
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = secondaryColor.get, _isOptional = true, description = "be in same location as " + secondaryColor.get))



      description = "Your task is to use chemistry to create " + secondaryColor.get + ". When you are done, focus on the " + secondaryColor.get + "."

    } else if (mode == MODE_CHEMISTRY_MIX_PAINT_TERTIARY) {

      gSequence.append(new GoalFind(objectName = secondaryColor.get, failIfWrong = true, _defocusOnSuccess = true, description = "focus on the intermediate mixing result (" + secondaryColor.get + ")"))
      gSequence.append(new GoalFind(objectName = tertiaryColor.get, failIfWrong = true, description = "focus on the final mixing result (" + tertiaryColor.get + ")"))

      gSequenceUnordered.append( new GoalMoveToNewLocation(_isOptional = true, unlessInLocation = paintLocation.get, description = "move to a new location (unless starting in task location)") )            // Move to any new location
      gSequenceUnordered.append( new GoalMoveToLocation(paintLocation.get, _isOptional = true, description = "move to the location of the paint") )

      // Secondary
      for (inputChemical <- inputColorsSecondary) {
        gSequenceUnordered.append(new GoalInRoomWithObject(objectName = inputChemical, _isOptional = true, description = "be in same location as " + inputChemical))
      }
      gSequenceUnordered.append(new GoalObjectsInSingleContainer(objectNames = inputColorsSecondary, _isOptional = true, description = "have all ingredients (secondary) alone in a single container"))
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = secondaryColor.get, _isOptional = true, description = "be in same location as (secondary) " + secondaryColor.get, key = "secondary"))
      // Tertiary
      //gSequenceUnordered.append( new GoalActivateDeviceWithName(deviceName = timeDeviceName.get, description = "activate time keeping device (plane 2)", key = "aTime2", keysMustBeCompletedBefore = Array("b2")) )
      for (inputChemical <- inputColorsTertiary) {
        gSequenceUnordered.append(new GoalInRoomWithObject(objectName = inputChemical, _isOptional = true, description = "be in same location as (tertiary) " + inputChemical, key = "tertiary_" + inputChemical, keysMustBeCompletedBefore = Array("secondary")))
      }
      gSequenceUnordered.append(new GoalObjectsInSingleContainer(objectNames = inputColorsTertiary, _isOptional = true, description = "have all ingredients (tertiary) alone in a single container"))
      gSequenceUnordered.append(new GoalInRoomWithObject(objectName = tertiaryColor.get, _isOptional = true, description = "be in same location as " + tertiaryColor.get))


      description = "Your task is to use chemistry to create " + tertiaryColor.get + ". When you are part-way done, focus on the intermediate (secondary color) paint you created.  When you are completely done, focus on the " + secondaryColor.get + "."

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
    if (mode == MODE_CHEMISTRY_MIX_PAINT_SECONDARY) {
      return mkGoldActionSequenceMixPaint(modifiers, runner)
    } else if (mode == MODE_CHEMISTRY_MIX_PAINT_TERTIARY) {
      return mkGoldActionSequenceMixPaint(modifiers, runner)
    } else {
      throw new RuntimeException("ERROR: Unrecognized task mode: " + mode)
    }

  }

  /*
   * Gold action sequences
   */
  def mkGoldActionSequenceMixPaint(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String]) = {
    val universe = runner.agentInterface.get.universe
    val agent = runner.agentInterface.get.agent

    // Task variables
    val secondaryColor = this.getTaskValueStr(modifiers, "secondaryColor")
    if (secondaryColor.isEmpty) throw new RuntimeException("ERROR: Failed to find secondary color in task setup.")
    val tertiaryColor = this.getTaskValueStr(modifiers, "tertiaryColor")
    if (tertiaryColor.isEmpty) throw new RuntimeException("ERROR: Failed to find tertiary color in task setup.")
    val inputColorsSecondary = this.getTaskValueStr(modifiers, "inputChemicalsSecondary").get.split(",")
    val inputColorsTertiary = this.getTaskValueStr(modifiers, "inputChemicalsTertiary").get.split(",")

    val paintLocation = this.getTaskValueStr(modifiers, "location")

    val mixRequirements = ("violet paint" -> Array("red paint", "blue paint"),
      "green paint" -> Array("blue paint", "yellow paint"),
      "orange paint" -> Array("yellow paint", "red paint"),
      "yellow-orange paint" -> Array("yellow paint", "orange paint"),
      "red-orange paint" -> Array("red paint", "orange paint"),
      "violet-red paint" -> Array("red paint", "violet paint"),
      "blue-violet paint" -> Array("blue paint", "violet paint"),
      "green-blue paint" -> Array("green paint", "blue paint"),
      "yellow-green paint" -> Array("green paint", "yellow paint")
    )

    // Step 1: Find the location with the paints
    val startLocation1 = agent.getContainer().get.name
    val actionStrsSearchPattern1 = PathFinder.createActionSequenceSearchPatternPrecomputed(universe, agent, startLocation1)

    // Walk around the environment until we find the location with the paints
    var substances = Set[EnvObject]()
    breakable {
      for (searchPatternStep <- actionStrsSearchPattern1) {
        // First, check to see if the object is here
        val curLocSearch = PathFinder.getEnvObject(queryName = getCurrentAgentLocation(runner).name, universe) // Get a pointer to the whole room the answer box is in
        substances = curLocSearch.get.getContainedAccessibleObjectsOfType[Paint]()     // Look for a location that has paints

        if (substances.size >= 3) {
          // Paint location found -- we can stop traversing the environment
          break
        }

        // If not found, move to next location to continue search
        runActionSequence(searchPatternStep, runner)
      }

      // First, check to see if the object is here
      val curLocSearch = PathFinder.getEnvObject(queryName = getCurrentAgentLocation(runner).name, universe) // Get a pointer to the whole room the answer box is in
      substances = curLocSearch.get.getContainedAccessibleObjectsOfType[Paint]()     // Look for a location that has paints

    }

    // Check that we successfully found the paints -- if not, fail
    if (substances.size == 0) {
      // Fail
      return (false, getActionHistory(runner))
    }

    runAction("look around", runner)

    // Step N: Find an empty container to do the mixing
    var mixingContainer:Option[EnvObject] = None
    val possibleContainers = getCurrentAgentLocation(runner).getContainedAccessibleObjectsOfType[Container]()
    breakable {
      for (container <- possibleContainers) {
        // Check that it's empty, and open
        if ((container.getContainedObjects(includeHidden = false).size == 0) && (container.propContainer.get.isOpen == true)) {
          mixingContainer = Some(container)
          break
        }
      }
    }

    if (mixingContainer.isEmpty) {
      // Fail
      return (false, getActionHistory(runner))
    }

    // Step N: Mix secondary colour
    // Step NA: Move all components into the container
    for (inputColor <- inputColorsSecondary) {
      val substance = PathFinder.getAllAccessibleEnvObject(inputColor, getCurrentAgentLocation(runner))(0)
      //runAction("move " + PathFinder.getObjUniqueReferent(substance, getCurrentAgentLocation(runner)).get + " to " + PathFinder.getObjUniqueReferent(mixingContainer.get, getCurrentAgentLocation(runner)).get, runner)
      val paintContainer = substance.getContainer()
      runAction("pour " + PathFinder.getObjUniqueReferent(paintContainer.get, getCurrentAgentLocation(runner)).get + " in " + PathFinder.getObjUniqueReferent(mixingContainer.get, getCurrentAgentLocation(runner)).get, runner)
    }

    // Step NB: Mix
    runAction("mix " + PathFinder.getObjUniqueReferent(mixingContainer.get, getCurrentAgentLocation(runner)).get, runner)


    // Look around
    runAction("look around", runner)

    // Step N: Focus on substance
    val mixingResult1 = PathFinder.getAllAccessibleEnvObject(secondaryColor.get, getCurrentAgentLocation(runner))
    if (mixingResult1.size == 0) return (false, getActionHistory(runner))
    runAction("focus on " + PathFinder.getObjUniqueReferent(mixingResult1(0), getCurrentAgentLocation(runner)).get, runner)

    // Wait one moment
    runAction("wait1", runner)


    // Stop point -- check if we only need to mix secondary paint colour
    if (mode == MODE_CHEMISTRY_MIX_PAINT_SECONDARY) {
      // Stop here
      return (true, getActionHistory(runner))
    }


    // Next step -- tertiary paint colour

    // Step N: Open paint cupboard to get access to more paints


    // Step N: Mix tertiary colour

    var attempts = 0
    // Step NA: Move all components into the container
    var substance = Array.empty[EnvObject]
    while (substance.length == 0) {
      for (inputColor <- inputColorsTertiary) {
        breakable {
          var successOpeningContainers:Boolean = true
          for (i <- 0 to 10) {
            substance = PathFinder.getAllAccessibleEnvObject(inputColor, getCurrentAgentLocation(runner))
            if (substance.size > 0) break // Found at least one substance matching the criteria
            // If we reach here, we didn't find a substance -- start opening closed containers
            if (successOpeningContainers) {
              successOpeningContainers = PathFinder.openRandomClosedContainer(currentLocation = getCurrentAgentLocation(runner), runner)
            }
          }
        }

        // Check for failure
        if (substance.length == 0) {
          // For some reason we weren't able to find the substance, even after opening multiple containers.  Let's try moving to a different location and trying once more.
          attempts += 1

          if (attempts > 1) {
            // fail
            return (false, getActionHistory(runner))
          } else {
            // Pick up container
            val containerReferent = PathFinder.getObjUniqueReferent(mixingContainer.get, getCurrentAgentLocation(runner))
            println("Container referent: " + containerReferent)
            println(runner.currentHistory.toString())
            runAction("pick up " + containerReferent.get, runner)

            // Move to another spot
            val startLocation = agent.getContainer().get.name
            var endLocation = "art studio"
            if (startLocation == "art studio") endLocation = "workshop"
            val (actions, actionStrs) = PathFinder.createActionSequence(universe, agent, startLocation, endLocation)
            runActionSequence(actionStrs, runner)

            // Drop container
            runAction("drop " + mixingContainer.get.name + " in inventory", runner)

            // Look around
            runAction("look around", runner)
          }

        } else {
          //runAction("move " + PathFinder.getObjUniqueReferent(substance, getCurrentAgentLocation(runner)).get + " to " + PathFinder.getObjUniqueReferent(mixingContainer.get, getCurrentAgentLocation(runner)).get, runner)
          val paintContainer = substance(0).getContainer()
          runAction("pour " + PathFinder.getObjUniqueReferent(paintContainer.get, getCurrentAgentLocation(runner)).get + " in " + PathFinder.getObjUniqueReferent(mixingContainer.get, getCurrentAgentLocation(runner)).get, runner)
        }
      }
    }


    // Step NB: Mix
    runAction("mix " + PathFinder.getObjUniqueReferent(mixingContainer.get, getCurrentAgentLocation(runner)).get, runner)


    // Look around
    runAction("look around", runner)

    // Step N: Focus on substance
    val mixingResult2 = PathFinder.getAllAccessibleEnvObject(tertiaryColor.get, getCurrentAgentLocation(runner))
    if (mixingResult2.size == 0) return (false, getActionHistory(runner))
    runAction("focus on " + PathFinder.getObjUniqueReferent(mixingResult2(0), getCurrentAgentLocation(runner)).get, runner)

    // Wait one moment
    runAction("wait1", runner)


    // Return
    return (true, getActionHistory(runner))
  }


}


object TaskChemistryMixPaint {
  val MODE_CHEMISTRY_MIX_PAINT_SECONDARY       = "chemistry mix paint (secondary color)"
  val MODE_CHEMISTRY_MIX_PAINT_TERTIARY        = "chemistry mix paint (tertiary color)"

  def registerTasks(taskMaker:TaskMaker1): Unit = {
    taskMaker.addTask( new TaskChemistryMixPaint(mode = MODE_CHEMISTRY_MIX_PAINT_SECONDARY) )
    taskMaker.addTask( new TaskChemistryMixPaint(mode = MODE_CHEMISTRY_MIX_PAINT_TERTIARY) )
  }

}
