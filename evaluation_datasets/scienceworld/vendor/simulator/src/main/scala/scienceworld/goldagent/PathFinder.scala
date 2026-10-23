package scienceworld.goldagent

import language.model.ActionRequestDef
import scienceworld.actions.{Action, ActionFocus, ActionLookAround, ActionMoveObject, ActionMoveThroughDoor, ActionOpenDoor}
import scienceworld.input.InputParser
import scienceworld.objects.agent.Agent
import scienceworld.objects.containers.Cup
import scienceworld.objects.devices.Sink
import scienceworld.objects.location.{Location, Universe}
import scienceworld.objects.substance.Water
import scienceworld.runtime.pythonapi.PythonInterface
import scienceworld.struct.EnvObject
import scienceworld.tasks.goals.ObjMonitor
import scienceworld.tasks.specifictasks.TaskParametric

import scala.collection.mutable
import scala.collection.mutable.ArrayBuffer
import scala.reflect.ClassTag
import scala.util.Random
import scala.util.control.Breaks._


/*
 * Tools for generating gold trajectories/action sequences.
 */


object PathFinder {
  val precomputedExhaustivePaths = mutable.Map[String, Array[Array[String]]]()  // Key: Start location, value: Path


  def createActionSequence(universe:EnvObject, agent:Agent, startLocation:String, endLocation:String): (Array[Action], Array[String]) = {
    val actionSequence = new ArrayBuffer[(Action, String)]

    val (success, pathLocations) = this.getLocationSequence(universe, startLocation, endLocation)
    if (!success) {
      // Fail gracefully
      //println ("Error: could not get location sequence")
      return (Array.empty[Action], Array.empty[String])
    }

    //println ("PathLocations: " + pathLocations.mkString(", "))

    for (i <- 0 until pathLocations.length-1) {
      val locationName = pathLocations(i)
      val nextLocationName = pathLocations(i+1)

      // Get the location object
      val location = this.getEnvObject(queryName = locationName, universe)
      if (location.isEmpty) {
        // Fail gracefully
        //println ("Error: location is empty")
        return (Array.empty[Action], Array.empty[String])
      }

      // Find the appropriate portal
      val portals = location.get.getPortals()
      for (portal <- portals) {
        if (portal.doesConnectTo(nextLocationName)) {
          // This is the portal that connects to the next location.

          // Get portal referent
          val portalReferents = portal.getReferents(location.get).toList.sortBy(ref => (-ref.length, ref))
          val portalReferent = portalReferents(0)   // Take the longest referent (least likely to be ambiguous)

          // Do we need to open it?
          // TODO: Add check?
          val actionOpenDoor = new ActionOpenDoor(ActionRequestDef.mkBlank(), assignments = Map("agent" -> agent, "door" -> portal))
          actionSequence.append( (actionOpenDoor, "open " + portalReferent) )

          // Now we need to go through it
          val actionMoveLocation = new ActionMoveThroughDoor(ActionRequestDef.mkBlank(), assignments = Map("agent" -> agent, "doorOrLocation" -> portal))
          actionSequence.append( (actionMoveLocation, "go to " + nextLocationName) )
        }

      }

    }


    // Convert to parallel arrays
    val actions = new ArrayBuffer[Action]
    val strs = new ArrayBuffer[String]
    for (i <- 0 until actionSequence.length) {
      actions.append( actionSequence(i)._1 )
      strs.append( actionSequence(i)._2 )
    }

    // Return
    return (actions.toArray, strs.toArray)
  }


  // Create an action sequence for an exhaustive search pattern, that travels to all locations
  def createActionSequenceSearchPattern(universe:EnvObject, agent:Agent, startLocation:String): (Array[Array[String]]) = {
    val actionSequenceSegments = new ArrayBuffer[Array[String]]

    val (success, pathLocations) = this.getSearchPathSequenceAllLocations(universe, startLocation)
    if (!success) {
      // Fail gracefully
      //println ("Error: could not get location sequence")
      return (Array.empty[Array[String]])
    }

    //println ("PathLocations: " + pathLocations.mkString(", "))

    for (i <- 0 until pathLocations.length-1) {
      val locationName = pathLocations(i)
      val nextLocationName = pathLocations(i+1)

      // Get the location object
      val location = this.getEnvObject(queryName = locationName, universe)
      if (location.isEmpty) {
        // Fail gracefully
        //println ("Error: location is empty")
        return (Array.empty[Array[String]])
      }

      val segmentActions = new ArrayBuffer[String]

      // Find the appropriate portal
      val portals = location.get.getPortals()
      for (portal <- portals) {
        if (portal.doesConnectTo(nextLocationName)) {
          // This is the portal that connects to the next location.

          // Get portal referent
          val portalReferents = portal.getReferents(location.get).toList.sortBy(ref => (-ref.length, ref))
          val portalReferent = portalReferents(0)   // Take the longest referent (least likely to be ambiguous)

          // Do we need to open it?
          // TODO: Add check?
          val actionOpenDoor = new ActionOpenDoor(ActionRequestDef.mkBlank(), assignments = Map("agent" -> agent, "door" -> portal))
          //actionSequence.append( (actionOpenDoor, "open " + portalReferent) )
          segmentActions.append("open " + portalReferent)

          // Now we need to go through it
          val actionMoveLocation = new ActionMoveThroughDoor(ActionRequestDef.mkBlank(), assignments = Map("agent" -> agent, "doorOrLocation" -> portal))
          //actionSequence.append( (actionMoveLocation, "go to " + nextLocationName) )
          segmentActions.append("go to " + nextLocationName)

        }

      }

      actionSequenceSegments.append( segmentActions.toArray )

    }

    // Return
    return (actionSequenceSegments.toArray)
  }

  // Stores previously computed paths, for speed.
  // Assumes that critical aspects of the environment (e.g. doors being closed) does not change between runs.
  def createActionSequenceSearchPatternPrecomputed(universe:EnvObject, agent:Agent, startLocation:String): (Array[Array[String]]) = {
    if (!precomputedExhaustivePaths.contains(startLocation) ) {
      precomputedExhaustivePaths(startLocation) = createActionSequenceSearchPattern(universe, agent, startLocation)
    }

    return precomputedExhaustivePaths(startLocation)
  }

  // Find a valid path (sequence of locations) from a starting location to an end location.
  // Returns (success, array(location names) )
  def getLocationSequence(universe:EnvObject, startLocation:String, endLocation:String, maxSteps:Int = 10):(Boolean, Array[String]) = {
    val validTransitions = this.buildLocationGraph(universe)

    // Edge case: Start and end location are the same
    if (sanitize(startLocation) == sanitize(endLocation)) return (true, Array.empty[String])

    // Start: Populate with single path with single step (current start location)
    var curExhaustivePaths = Array( Array(startLocation) )

    var curSteps:Int = 0
    while (curSteps < maxSteps) {
      // Add to each path
      curExhaustivePaths = mkExhaustivePathsOneStepLonger(curExhaustivePaths, validTransitions)

      // Check for a successful path from start to finish
      for (path <- curExhaustivePaths) {
        if (sanitize(path.last) == sanitize(endLocation)) {
          // Found a valid path
          return (true, path)
        }
      }

      curSteps += 1
    }

    // If we reach here, then we timed out -- no successful path was found
    return (false, Array.empty[String])
  }


  // Make a search path from the current location that covers ALL locations
  def getSearchPathSequenceAllLocations(universe:EnvObject, startLocation:String, maxSteps:Int = 20):(Boolean, Array[String]) = {
    val validTransitions = this.buildLocationGraph(universe)
    val allLocationNames = validTransitions.keySet


    // Start: Populate with single path with single step (current start location)
    var curExhaustivePaths = Array( Array(startLocation) )

    var curSteps:Int = 0
    while (curSteps < maxSteps) {
      // Add to each path
      curExhaustivePaths = mkExhaustivePathsOneStepLonger(curExhaustivePaths, validTransitions)

      // Check for a successful path that includes all locations
      for (path <- curExhaustivePaths) {
        val pathLocations = path.toSet
        if (pathLocations.size == allLocationNames.size) {
          // Found a valid path
          return (true, path)
        }
      }

      curSteps += 1
    }

    // If we reach here, then we timed out -- no successful path was found
    return (false, Array.empty[String])
  }


  // Make exhaustive paths one step longer
  def mkExhaustivePathsOneStepLonger(curPaths:Array[Array[String]], validTransitions:Map[String, Array[String]]):Array[Array[String]] = {
    val out = new ArrayBuffer[ Array[String] ]

    for (inPath <- curPaths) {
      val curLoc = inPath.last
      val possibleTransitions = validTransitions(curLoc)
      for (newLoc <- scala.util.Random.shuffle(possibleTransitions.toList)) {     // Shuffles the order, so different routes might be chosen
        out.append ( inPath ++ Array(newLoc) )
      }
    }

    out.toArray
  }


  // Builds a graph of where one can go (through portals) from each location
  def buildLocationGraph(universe:EnvObject):Map[String, Array[String]] = {
    val validTransitions = mutable.Map[String, Array[String]]()
    val allObjects = universe.getContainedObjectsAndPortalsRecursive(true)
    val allLocations = allObjects.filter(_.isInstanceOf[Location]).toArray

    //println ("Number of locations: " + allLocations.length)
    //println ("Locations: " + allLocations.map(_.name).mkString(", "))

    for (location <- allLocations) {
      val transitions = new ArrayBuffer[String]
      val portals = location.getPortals(includeHidden = false)
      for (portal <- portals) {
        for (connectionPoint <- portal.getConnectionPoints()) {
          if (sanitize(connectionPoint.name) != sanitize(location.name)) {
            transitions.append(connectionPoint.name)
          }
        }
      }

      validTransitions(location.name) = transitions.toArray
    }

    /*
    for (key <- validTransitions.keySet) {
      println ("\t" + key.formatted("%20s") + "\t" + validTransitions(key).mkString(", "))
    }
     */

    return validTransitions.toMap
  }



  /*
   * Action helpers
   */

  // Generate an action to focus on an object
  def actionFocusOnObject(obj:EnvObject, agent:Agent, locationPerspective:EnvObject): (Action, String) = {
    val actionFocus = new ActionFocus(ActionRequestDef.mkBlank(), assignments = Map("agent" -> agent, "obj" -> obj), objMonitor = new ObjMonitor())   //## new objMonitor
    //val actionStr = "focus on " + this.getObjReferent(obj)
    val referentObj = this.getObjUniqueReferent(obj, locationPerspective)
    if (referentObj.isEmpty) return (actionFocus, "ERROR FINDING UNIQUE REFERENT FOR (" + obj.name + ")")

    val actionStr = "focus on " + referentObj.get
    return (actionFocus, actionStr)
  }

  // Move an object from one location to another location
  def actionMoveObject(obj:EnvObject, destination:EnvObject, agent:Agent, locationPerspective:EnvObject): (Action, String) = {
    val actionMove = new ActionMoveObject(ActionRequestDef.mkBlank(), assignments = Map("agent" -> agent, "obj" -> obj, "moveTo" -> destination))
    // val actionStr = "move " + this.getObjReferent(obj) + " to " + this.getObjReferent(destination)

    val referentObj = this.getObjUniqueReferent(obj, locationPerspective)
    if (referentObj.isEmpty) return (actionMove, "ERROR FINDING UNIQUE REFERENT FOR (" + obj.name + ")")

    val referentDest = this.getObjUniqueReferent(destination, locationPerspective)
    if (referentDest.isEmpty) return (actionMove, "ERROR FINDING UNIQUE REFERENT FOR (" + destination.name + ")")

    val actionStr = "move " + referentObj.get + " to " + referentDest.get
    return (actionMove, actionStr)
  }

  // Move objects KNOWN TO BE IN THE INVENTORY to a new destination
  def actionMoveObjectFromInventory(obj:EnvObject, destination:EnvObject, agent:Agent, locationPerspective:EnvObject): (Action, String) = {
    val actionMove = new ActionMoveObject(ActionRequestDef.mkBlank(), assignments = Map("agent" -> agent, "obj" -> obj, "moveTo" -> destination))
    // val actionStr = "move " + this.getObjReferent(obj) + " to " + this.getObjReferent(destination)

    val referentObj = this.getObjReferent(obj) + " in inventory"

    val referentDest = this.getObjUniqueReferent(destination, locationPerspective)
    if (referentDest.isEmpty) return (actionMove, "ERROR FINDING UNIQUE REFERENT FOR (" + destination.name + ")")

    val actionStr = "move " + referentObj + " to " + referentDest.get
    return (actionMove, actionStr)
  }

  // Pick up an object and place it in the inventory
  def actionPickUpObject(obj:EnvObject, agent:Agent, locationPerspective:EnvObject): (Action, String) = {
    val inventory = this.getEnvObject(queryName = "inventory", agent).get

    val actionMove = new ActionMoveObject(ActionRequestDef.mkBlank(), assignments = Map("agent" -> agent, "obj" -> obj, "moveTo" -> inventory))
    // val actionStr = "move " + this.getObjReferent(obj) + " to " + this.getObjReferent(destination)

    val referentObj = this.getObjUniqueReferent(obj, locationPerspective)
    if (referentObj.isEmpty) return (actionMove, "ERROR FINDING UNIQUE REFERENT FOR (" + obj.name + ")")

    val referentDest = "inventory"

    val actionStr = "pick up " + referentObj.get
    return (actionMove, actionStr)
  }


  def actionLookAround(agent:Agent):(Action, String) = {
    val actionLookAround = new ActionLookAround(ActionRequestDef.mkBlank(), assignments = Map("agent" -> agent))
    val actionStr = "look around"
    return (actionLookAround, actionStr)
  }


  // Get a likely OK referent name for an object
  def getObjReferent(obj:EnvObject): String = {
    val referents = obj.getReferents().toList.sortBy(ref => (-ref.length, ref))
    val referent = referents(0)   // Take the longest referent (least likely to be ambiguous)
    return referent
  }

  def getObjUniqueReferent(obj:EnvObject, agentLocation:EnvObject):Option[String] = {
    // Collect all unique referents for all objects in this location
    val uniqueReferents = InputParser.getAllUniqueReferents(agentLocation, includeHidden = true, recursive = true)

    // Go through the returned list, look for the object of interest and return its unique referent from this perspective
    for (tuple <- uniqueReferents) {
      val referent = tuple._1
      val referentObj = tuple._2
      if (referentObj == obj) {
        //## (TODO, keep this here for a while to make sure that it throws an error if there are bad referents being generated)
        if ((referent.length < 2) || (referent.startsWith(" ")) || (referent.contains("  "))) {
          println("*Potential referent issue identified:* " )
          println("referent: " + referent + "\t referentObj: " + referentObj.toStringMinimal() + " \t obj: " + obj.toStringMinimal())
          sys.exit(1)
        }
        return Some(referent)
      }

      //println("referent: " + referent + "\t referentObj: " + referentObj.toStringMinimal() + " \t obj: " + obj.toStringMinimal())
    }

    // If we reach here, the object was not found
    return None
  }


  /*
   * High-level helpers
   */
  def openRandomClosedContainer(currentLocation:EnvObject, runner:PythonInterface): Boolean = {
    val allObjs = currentLocation.getContainedAccessibleObjects(includeHidden = false)
    for (obj <- Random.shuffle(allObjs.toList)) {
      if ((obj.propContainer.isDefined) && (obj.propContainer.get.isContainer) && (obj.propContainer.get.isOpen == false) && (obj.propContainer.get.isClosable)) {
        // Try to open this container
        TaskParametric.runAction("open " + PathFinder.getObjUniqueReferent(obj, currentLocation).get, runner)
        //TaskParametric.runAction("open " + obj.getReferents().mkString(", "), runner)
        return true
      }
    }

    // If we reach here, no more containers to open
    return false
  }

  // Attempts to get water from the current location.  Finds a cup-like object, and attempts to transfer water into the cup.
  // Returns (success, container reference, water reference)
  def getWaterInContainer(runner:PythonInterface, useInventoryContainer:Option[EnvObject] = None):(Boolean, Option[EnvObject], Option[EnvObject]) = {
    // Get current agent location
    val curLocation = TaskParametric.getCurrentAgentLocation(runner)

    // Look for a container (cup-like)
    // TODO: Add parameter for preferred container?
    val cups = curLocation.getContainedAccessibleObjectsOfType[Cup]()
    var cup:Option[EnvObject] = None
    if (useInventoryContainer.isDefined) {
      cup = useInventoryContainer
    } else {
      breakable {
        for (cup_ <- cups) {
          if (cup_.getContainedObjects(includeHidden = false).size == 0) {
            cup = Some(cup_)
            break()
          }
        }
      }

      if (cup.isEmpty) {
        // ERROR: Can't find a cup
        return (false, None, None)
      }
    }

    // Attempt 1: Look for any sinks
    val sinks = curLocation.getContainedAccessibleObjectsOfType[Sink]().toArray
    if (sinks.size > 0) {
      val sink = sinks(0)
      // Put container in sink
      TaskParametric.runAction("move " + PathFinder.getObjUniqueReferent(cup.get, curLocation).get + " to " + PathFinder.getObjUniqueReferent(sink, curLocation).get, runner)
      // Turn on sink
      TaskParametric.runAction("activate " + PathFinder.getObjUniqueReferent(sink, curLocation).get, runner)
      // Turn off sink
      TaskParametric.runAction("deactivate " + PathFinder.getObjUniqueReferent(sink, curLocation).get, runner)

      val water = cup.get.getContainedAccessibleObjectsOfType[Water]().toArray

      if (water.size > 0) {
        // Sink worked -- return
        if (useInventoryContainer.isDefined) TaskParametric.runAction("pick up " + PathFinder.getObjUniqueReferent(cup.get, curLocation).get, runner)
        return (true, cup, Some(water(0)))
      }
    }

    // Attempt 2: Look for anything else that might have available water
    val accessibleWater = curLocation.getContainedAccessibleObjectsOfType[Water]()
    if (accessibleWater.size > 0) {
      for (water <- accessibleWater) {
        val waterContainer = water.getContainer().get
        TaskParametric.runAction("dunk " + PathFinder.getObjUniqueReferent(cup.get, curLocation).get + " into " + PathFinder.getObjUniqueReferent(waterContainer, curLocation).get, runner)

        if (cup.get.getContainedAccessibleObjectsOfType[Water]().size > 0) {
          // If the transfer was successful, return
          if (useInventoryContainer.isDefined) TaskParametric.runAction("pick up " + PathFinder.getObjUniqueReferent(cup.get, curLocation).get, runner)
          return (true, cup, Some(water))
        }
      }
    }


    if (useInventoryContainer.isDefined) TaskParametric.runAction("pick up " + PathFinder.getObjUniqueReferent(cup.get, curLocation).get, runner)

    // If we reach here, the agent was not able to find any accessible water
    return (false, None, None)
  }


  /*
   * Helpers
   */

  // Find an object in the universe by name
  def getEnvObject(queryName:String, universe:EnvObject):Option[EnvObject] = {
    val allObjects = universe.getContainedObjectsAndPortalsRecursive(true)
    for (obj <- allObjects) {
      if ((sanitize(obj.name) == sanitize(queryName)) || (sanitize(obj.getDescriptName()) == sanitize(queryName))) {
        return Some(obj)
      }
    }

    // Default return
    None
  }

  // Find all objects with a given name in the universe
  def getAllEnvObject(queryName:String, universe:EnvObject):Array[EnvObject] = {
    val allObjects = universe.getContainedObjectsAndPortalsRecursive(true)
    val out = new ArrayBuffer[EnvObject]

    for (obj <- allObjects) {
      if ((sanitize(obj.name) == sanitize(queryName)) || (sanitize(obj.getDescriptName()) == sanitize(queryName))) {
        out.append(obj)
      }
    }

    // Default return
    out.toArray
  }

  // Find all objects with a given name in the universe
  def getAllAccessibleEnvObject(queryName:String, universe:EnvObject):Array[EnvObject] = {
    val allObjects = universe.getContainedAccessibleObjects(true, includePortals = true)
    val out = new ArrayBuffer[EnvObject]

    for (obj <- allObjects) {
      if ((sanitize(obj.name) == sanitize(queryName)) || (sanitize(obj.getDescriptName()) == sanitize(queryName))) {
        out.append(obj)
      }
    }

    // Default return
    out.toArray
  }

  // Sanitize strings for comparison
  private def sanitize(name:String):String = {
    return name.trim().toLowerCase
  }



}
