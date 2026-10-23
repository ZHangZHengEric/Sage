package scienceworld.runtime

import language.model.{ActionRequestDef, ActionTrigger, ParamSig, ParamSigList}
import main.scala.scienceworld.runtime.SimplifierProcessor
import scienceworld.actions.{Action, ActionInventory, ActionLookAround, ActionTaskDesc}
import scienceworld.input.{ActionDefinitions, ActionHandler, ExampleAction, InputParser}
import scienceworld.objects.agent.Agent
import scienceworld.objects.electricalcomponent.Terminal
import scienceworld.runtime.pythonapi.TemplateAction
import scienceworld.struct.EnvObject
import scienceworld.tasks.Task
import scienceworld.tasks.goals.{GoalSequence, ObjMonitor}

import scala.collection.mutable
import scala.collection.mutable.ArrayBuffer
import scala.io.StdIn.readLine
import scala.util.control.Breaks._

class AgentInterface(val universe:EnvObject, val agent:Agent, val task:Task, var simplificationStr:String = "") {

  val objMonitor = new ObjMonitor()
  // Store whether the environment is in an unexpected error state
  var errorState:Boolean = false
  var errorMessage:String = ""

  // Add any task-specific objects to the agent's inventory
  // TODO: Currently places task objects in agents inventory
  for (taskObject <- task.taskObjects) {
    agent.getInventoryContainer().addObject(taskObject)
  }

  // Store a copy of the task description in the agent, for easy access through the action space
  agent.setTaskDescription(this.getTaskDescription())

  // Simplifications -- Interpret 'easy' to mean a specific set of settings
  if (simplificationStr == "easy") {
    if (task.taskName.toLowerCase.contains("power-component") || task.taskName.toLowerCase.contains("conductivity")) {
      simplificationStr = "teleportAction,openDoors,selfWateringFlowerPots"
    } else {
      simplificationStr = "teleportAction,noElectricalAction,openDoors,selfWateringFlowerPots"
    }
  }

  // Run any simplifications that need to be run at initialization
  val (simplifierSuccess, simplifierErrStr) = SimplifierProcessor.parseSimplificationStr(simplificationStr)
  if (!simplifierSuccess) this.setErrorState(simplifierErrStr)
  println ("Selected simplifications: " + SimplifierProcessor.getSimplificationsUsed())
  SimplifierProcessor.runSimplificationsInitialization(universe, agent)

  // Action handler (must be run after simplifications -- as simplifications can affect action space)
  val actionHandler = ActionDefinitions.mkActionDefinitions()

  // Input parser
  val inputParser = new InputParser(actionHandler.getActions())


  private var curIter:Int = 0

  /*
   * Objects visible to the agent
   */

  // TODO: Currently just returns the current room, rather than a list of all visible objects
  def getAgentVisibleObjects(includeHidden:Boolean = false):(Boolean, EnvObject)  = {
    val agentContainer = agent.getContainer()
    if (agentContainer.isEmpty) {
      val errStr = "ERROR: Agent is not in container."
      return (false, new EnvObject)
    }

    //##val agentVisibleObjects = InputParser.collectAccessibleObjects(objectTreeRoot = agentContainer.get, includeHidden)
    return (true, agentContainer.get)
  }


  /*
   * Get possible actions/objects
   */
  def getPossibleActions(): Array[String] = {
    actionHandler.getActionExamplesPlainText().sorted
  }

  def getPossibleActionsWithIDs(): Array[ExampleAction] = {
    actionHandler.getActionExamplesPlainTextWithID()
  }

  def getPossibleActionsWithIDsJSON(): String = {
    val os = new StringBuilder

    // Special case: Check for parser being in ambiguity resolution state
    if (this.inputParser.isInAmbiguousState()) {
      val AMBIGUOUS_BASE_TEMPLATE_ID    = 100
      val ambiguousObjectUUIDs = this.inputParser.getAmbiguousObjectIDs()     // List of object IDs involved with each ambiguous choice

      val ambiguityResolutionChoices = this.getValidActionsAmbiguousState()
      val templatesJSONAmb = new ArrayBuffer[String]()

      var ambIdx:Int = 0
      for (choiceStr <- ambiguityResolutionChoices) {
        //templatesJSON.append( new TemplateAction(actionString = choiceStr, templateID = AMBIGUOUS_BASE_TEMPLATE_ID + ambIdx, objectIDs = ambiguousObjectUUIDs(ambIdx).toList, typeIDs = List.empty[Int]).toJSON() )    // TODO: Fix this casting (proper template ID, object IDs, etc)
        templatesJSONAmb.append("{\"action_example\":\"" + choiceStr + "\", \"template_id\":" + AMBIGUOUS_BASE_TEMPLATE_ID + ambIdx + "}" )
        ambIdx += 1
      }
      val outJSON = ("[" + templatesJSONAmb.mkString(", ") + "]")
      return outJSON
    }

    val templates = actionHandler.getActionExamplesPlainTextWithID()
    val templateJSON = templates.map(_.toJSON())
    os.append("[" + templateJSON.mkString(", ") + "]")

    os.toString()
  }


  def getPossibleObjects(): Array[String] = {
    val referents = InputParser.getAllUniqueReferents(this.getAgentVisibleObjects()._2, includeHidden = false).map(_._1)
    return referents
  }

  def getPossibleObjectReferentLUT():Map[Long, String] = {
    val uuid2referentLUT = inputParser.getAllUniqueReferentsLUT(this.getAgentVisibleObjects()._2, includeHidden = false)
    return uuid2referentLUT
  }

  def getPossibleObjectReferentTypesLUTJSON():String = {
    return inputParser.getAllUniqueReferentsWithTypeLUTJSON(this.getAgentVisibleObjects()._2, includeHidden = false)
  }

  def getPossibleObjectReferentLUTJSON():String = {
    val uuid2referentLUT = this.getPossibleObjectReferentLUT()

    val elems = new ArrayBuffer[String]
    for (key <- uuid2referentLUT.keySet.toArray.sorted) {
      elems.append( "\"" + key + "\": \"" + uuid2referentLUT(key) + "\"")
    }

    return "{" + elems.mkString(", ") + "}"
  }

  def getAllObjectTypesLUT():Map[Long, Long] = {
    val allObjs = InputParser.collectObjects(universe, includeHidden=true).toArray

    val lut = mutable.Map[Long, Long]()
    for (obj <- allObjs) {
      lut(obj.uuid) = obj.typeID
    }

    return lut.toMap
  }

  def getAllObjectTypesLUTJSON():String = {
    val uuid2typeLUT = this.getAllObjectTypesLUT()

    val elems = new ArrayBuffer[String]
    for (key <- uuid2typeLUT.keySet.toArray.sorted) {
      elems.append( "\"" + key + "\": \"" + uuid2typeLUT(key) + "\"")
    }

    return "{" + elems.mkString(", ") + "}"

  }

  // Get a LUT of {object_id: {type_id, referent:[]} values for the entire universe.
  def getAllObjectIdsTypesReferentsLUTJSON(): String = {
    val allObjs = InputParser.collectObjects(universe, includeHidden=true).toArray.sortBy(_.uuid)

    val elems = new ArrayBuffer[String]
    for (obj <- allObjs) {
      //println(obj.name)
      // If the electrical simplification is enabled, then remove all electrical terminals from the output list
      var filter:Boolean = false
      if (SimplifierProcessor.isSimplificationEnabled(SimplifierProcessor.SIMPLIFICATION_NO_ELECTRICAL_ACTION)) {
        obj match {
          case term:Terminal => { filter = true }
          case _ => {
            // Do nothing
          }
        }
      }

      if (!filter) {
        val uuid = obj.uuid
        val typeId = obj.typeID
        val referents = obj.getReferents()
        val referentsProcessed = new ArrayBuffer[String]
        for (referent <- referents.toArray.sorted) {
          referentsProcessed.append("\"" + referent + "\"")
        }

        val json = "\"" + uuid + "\":{ \"type_id\":" + typeId + ", \"referents\":[" + referentsProcessed.mkString(", ") + "] }"
        elems.append(json)
      }
    }

    val jsonOut = "{ " + elems.mkString(", ") + " }"
    return jsonOut
  }

  // Returns the valid actions available (centrally, number choices) if the parser is in an ambiguity resolution state
  def getValidActionsAmbiguousState():Array[String] = {
    if (!this.inputParser.isInAmbiguousState()) return Array.empty[String]

    val out = new ArrayBuffer[String]()   // e.g. Array("0", "1", "2", "3", etc)
    for (i <- 0 until this.inputParser.getNumAmbiguousMatches()) {
      out.append( i.toString )
    }

    return out.toArray
  }

  // Returns a list of only the valid action-agent combinations
  def getValidActionObjectCombinations(): Array[String] = {
    // Special case: Check for parser being in ambiguity resolution state
    if (this.inputParser.isInAmbiguousState()) return this.getValidActionsAmbiguousState()

    // Collect all objects visible to the agent
    val visibleObjTreeRoot = this.getAgentVisibleObjects()._2
    val agentInventory = agent.getInventoryContainer()
    val allVisibleObjects = InputParser.collectObjects(visibleObjTreeRoot, includeHidden = false).toArray

    // Collect UUID -> Unique Referent LUT
    //val uuid2referentLUT = inputParser.getAllUniqueReferentsLUT(universe, includeHidden=true, recursive = true)   // Generate UUID LUT using *all* objects in the environment, instead of just visible
    //val uuid2referentLUT = inputParser.getAllUniqueReferentsLUT(visibleObjTreeRoot, includeHidden=true, recursive = true)   // Generate UUID LUT using *all* objects in the environment, instead of just visible
    val uuid2referentLUT = inputParser.getAllUniqueReferentsLUTObjList(allVisibleObjects, visibleObjTreeRoot, includeHidden=true, recursive = true)   // Generate UUID LUT using *all* objects in the environment, instead of just visible

    // For oracle actions
    val allObjects = InputParser.collectObjects(universe, includeHidden = true).toArray
    val uuid2referentLUTAll = inputParser.getAllUniqueReferentsLUTObjList(allObjects, visibleObjTreeRoot, includeHidden = true, recursive = true)

    // Generate all possible valid actions
    val validActions = ActionDefinitions.mkPossibleActions(agent, allVisibleObjects, allObjects, uuid2referentLUT, uuid2referentLUTAll)

    return validActions.map(_.mkHumanReadableStr())
  }

  def getValidActionObjectCombinationsJSON(): String = {
    // Special case: Check for parser being in ambiguity resolution state
    if (this.inputParser.isInAmbiguousState()) {
      val AMBIGUOUS_BASE_TEMPLATE_ID    = 100
      val ambiguousObjectUUIDs = this.inputParser.getAmbiguousObjectIDs()     // List of object IDs involved with each ambiguous choice

      val ambiguityResolutionChoices = this.getValidActionsAmbiguousState()
      val templatesJSON = new ArrayBuffer[String]()

      var ambIdx:Int = 0
      for (choiceStr <- ambiguityResolutionChoices) {
        templatesJSON.append( new TemplateAction(actionString = choiceStr, templateID = AMBIGUOUS_BASE_TEMPLATE_ID + ambIdx, objectIDs = ambiguousObjectUUIDs(ambIdx).toList, typeIDs = List.empty[Int]).toJSON() )    // TODO: Fix this casting (proper template ID, object IDs, etc)
        ambIdx += 1
      }
      val outJSON = "{\"validActions\": [" + templatesJSON.mkString(",") + "]" + "}"
      return outJSON
    }

    // Collect all objects visible to the agent
    val visibleObjTreeRoot = this.getAgentVisibleObjects()._2
    val agentInventory = agent.getInventoryContainer()
    val allVisibleObjects = InputParser.collectObjects(visibleObjTreeRoot, includeHidden = false).toArray

    // Collect UUID -> Unique Referent LUT
    //val uuid2referentLUT = inputParser.getAllUniqueReferentsLUT(universe, includeHidden=true, recursive = true)   // Generate UUID LUT using *all* objects in the environment, instead of just visible
    val uuid2referentLUT = inputParser.getAllUniqueReferentsLUTObjList(allVisibleObjects, visibleObjTreeRoot, includeHidden=true, recursive = true)   // Generate UUID LUT using *all* objects in the environment, instead of just visible

    // For oracle actions
    val allObjects = InputParser.collectObjects(universe, includeHidden = true).toArray
    val uuid2referentLUTAll = inputParser.getAllUniqueReferentsLUTObjList(allObjects, visibleObjTreeRoot, includeHidden = true, recursive = true)


    // Generate all possible valid actions
    val validActions = ActionDefinitions.mkPossibleActions(agent, allVisibleObjects, allObjects, uuid2referentLUT, uuid2referentLUTAll)

    // To templates
    val validActionsTemplates = validActions.map(_.toTemplate())
    val validActionTemplatesJSON = validActionsTemplates.map(_.toJSON())

    // To JSON
    val outJSON = "{\"validActions\": [" + validActionTemplatesJSON.mkString(",") + "]" + "}"

    return outJSON
  }



  def getPossibleActionObjectCombinations(): (Array[TemplateAction], Map[Int, String]) = {
    val OBJ_PLACEHOLDER_TOKEN = "OBJ"
    val START_TOKEN = "START "
    val END_TOKEN = " END"

    val outTemplates = new ArrayBuffer[TemplateAction]
    val outObjectIdxLUT = mutable.Map[Int, String]()

    val objects = InputParser.getAllUniqueReferents(this.getAgentVisibleObjects()._2, includeHidden = false)

    // Special case: Check for parser being in ambiguity resolution state
    if (this.inputParser.isInAmbiguousState()) {
      val ambiguityResolutionChoices = this.getValidActionsAmbiguousState()
      val templates = new ArrayBuffer[TemplateAction]()
      for (choiceStr <- ambiguityResolutionChoices) {
        templates.append( new TemplateAction(actionString = choiceStr, templateID = 999, objectIDs = List.empty[Int], typeIDs = List.empty[Int]) )    // TODO: Fix this casting (proper template ID, object IDs, etc)
      }

      for (obj <- objects) {
        outObjectIdxLUT(obj._2.uuid.toInt) = obj._1     // TODO: Hacky, may not be correct.
      }
      return (templates.toArray, outObjectIdxLUT.toMap)
    }


    // Normal case
    val allActions = this.getPossibleActionsWithIDs()
    for (actionIdx <- 0 until allActions.length) {
      val actionStr = allActions(actionIdx).exampleStr

      val actionStr1 = START_TOKEN + actionStr + END_TOKEN
      val split = actionStr1.split(OBJ_PLACEHOLDER_TOKEN)

      // Number of objects to substitute
      val numPlaceholders = split.length - 1

      // Create all possible permutations of combinations of N objects
      val combos = objects combinations(numPlaceholders)
      for (combo <- combos) {
        for (perm <- combo.permutations) {
          val outStr = new StringBuilder
          val outObjs = new ArrayBuffer[EnvObject]

          for (i <- 0 until split.length) {
            outStr.append(split(i))
            if (i < (split.length - 1)) {
              val objReferent = perm(i)._1
              val obj = perm(i)._2
              outStr.append(objReferent)
              outObjs.append(obj)

              // Also add Object UUID and unique referent to LUT
              val objUUID = obj.uuid.toInt
              outObjectIdxLUT(objUUID) = objReferent
            }
          }
          // Remove start/end tokens
          val sanitizedOutStr = outStr.substring(START_TOKEN.length, outStr.length - END_TOKEN.length).trim
          val templateID = allActions(actionIdx).actionID   // Fetch unique template ID for this action template
          val objectUUIDs = outObjs.map(_.uuid).map(_.toInt).toList
          val objectTypeIDs = outObjs.map(_.typeID).map(_.toInt).toList

          // Pack
          val template = new TemplateAction(sanitizedOutStr, templateID, objectUUIDs, objectTypeIDs)

          // Store
          outTemplates.append(template)
        }
      }
    }

    // Return
    (outTemplates.toArray, outObjectIdxLUT.toMap)
  }

  def getPossibleActionObjectCombinationsJSON():String = {
    // Step 1: Get templates
    val (templates, uuidToRefLUT) = this.getPossibleActionObjectCombinations()

    // Step 2: Serialize templates to JSON
    val templatesJSON = templates.map(_.toJSON())

    // Step 3: Serialize LUT to JSON
    val jsonRecords = new ArrayBuffer[String]
    for (uuid <- uuidToRefLUT.keys.toArray.sorted) {
      jsonRecords.append("\"" + uuid + "\": \"" + uuidToRefLUT(uuid) + "\"")
    }
    val lutJSON = "{" + jsonRecords.mkString(",") + "}"

    // Step 4: Join JSONs together
    val outJSON = "{\"templates\": [" + templatesJSON.mkString(",") + "], \"lookUpTable\": " + lutJSON + "}"

    // Step 3: Return
    return outJSON
  }

  def getTaskDescription():String = {
    return this.task.description.trim()
  }

  def getCurIterations():Int = {
    return this.curIter
  }


  /*
   * Goal sequence monitoring
   */
  def getGoalProgressStr():String = {
    return this.task.goalSequence.getProgressString()
  }


  /*
   * Error Handling
   */
  def setErrorState(errorStr:String) {
    this.errorState = true
    this.errorMessage = errorStr
  }

  def isInErrorState():Boolean = {
    return this.errorState
  }

  def getErrorStateMessage():String = {
    return this.errorMessage
  }

  /*
   * User Input
   */
  def getUserInput():String = {
    print("> ")
    val inputStr = readLine()
    return inputStr
  }

  def processUserInput(inputStr:String, universe:EnvObject):(Boolean, String) = {   // (Success, statusString)
    val (successVisible, visibleObjects) = this.getAgentVisibleObjects()      // TODO: Currently just a reference to the container (current room), rather than a list

    if (!successVisible) throw new RuntimeException("ERROR: Agent is not in container.")

    // The agent's container (to render the agent's perspective)
    val agentContainer = agent.getContainer().get


    if (!this.inputParser.isInAmbiguousState()) {
      // Case 1: Normal case

      //val (successUserInput, errStr, userStr) = userInputParser.parse(inputStr, interpreter.objectTreeRoot, agent)
      val (successUserInput, errStr, userStr, action) = inputParser.parse(inputStr, visibleObjects, universe, agent, objMonitor, task.goalSequence, agentContainer)
      if (!successUserInput) {
        println("ERROR: " + errStr)
      } else {
        println(userStr)
        actionHandler.queueAction(action.get)
      }

      return (successUserInput, userStr)
    } else {
      // Case 2: Waiting to resolve an ambiguity

      // NOTE: Whether or not the ambiguity is resolved successfully, this will handle it and generate an appropriate user message.
      val (userStr, action) = inputParser.resolveAmbiguity(inputStr, agent, objMonitor, task.goalSequence)
      if (action.isDefined) {
        actionHandler.queueAction(action.get)
      }
      return (true, userStr)

    }

  }

  /*
   * Free actions
   */

  private def runFreeAction(action:Action):String = {
    // Check whether the simulator is in an error state (if so, return the error message)
    if (this.isInErrorState()) {
      return this.getErrorStateMessage()
    }

    actionHandler.queueAction(action)

    // Run queued actions
    val actionOutStr = actionHandler.runQueuedActions()

    return actionOutStr
  }

  def freeActionLook():String = {
    val actionRequest = new ActionRequestDef(name = ActionLookAround.ACTION_NAME, paramSigList = new ParamSigList(List.empty[ParamSig]), triggers = List.empty[ActionTrigger], uniqueActionID = ActionLookAround.ACTION_ID)
    val lut = Map[String, EnvObject]("agent" -> this.agent)
    val action = new ActionLookAround(actionRequest, lut)
    this.runFreeAction( action )
  }

  def freeActionInventory():String = {
    val actionRequest = new ActionRequestDef(name = ActionInventory.ACTION_NAME, paramSigList = new ParamSigList(List.empty[ParamSig]), triggers = List.empty[ActionTrigger], uniqueActionID = ActionInventory.ACTION_ID)
    val lut = Map[String, EnvObject]("agent" -> this.agent)
    val action = new ActionInventory(actionRequest, lut)
    this.runFreeAction( action )
  }

  def freeActionTaskDesc():String = {
    val actionRequest = new ActionRequestDef(name = ActionTaskDesc.ACTION_NAME, paramSigList = new ParamSigList(List.empty[ParamSig]), triggers = List.empty[ActionTrigger], uniqueActionID = ActionTaskDesc.ACTION_ID)
    val lut = Map[String, EnvObject]("agent" -> this.agent)
    val action = new ActionTaskDesc(actionRequest, lut)
    this.runFreeAction( action )
  }


  /*
   * Step
   */


  // Returns (observation, score, isCompleted)
  def step(userInputStr: String): (String, Double, Boolean) = {
    val userOutStr = new StringBuilder()


    // Check whether the simulator is in an error state (if so, return the error message)
    if (this.isInErrorState()) {
      return (this.getErrorStateMessage(), -1, true)
    }

    // Parse user input
    val (success, statusStr) = this.processUserInput(userInputStr, universe)

    /*
    // Uncomment to include the user input parse success/failure in the string (e.g. "successfully parsed action (look around)")
    if (statusStr.length > 0) {
      userOutStr.append("Input: " + statusStr + "\n\n")
    }
     */

    if (!success) {
      // If input was not successfully matched to an action, then do not continue/do a tick/etc:
      //println("### ERROR PARSING INPUT: " + statusStr)
      val score = task.goalSequence.score()
      val isCompleted = task.goalSequence.isCompleted()
      userOutStr.append(statusStr)
      return (userOutStr.toString(), score, isCompleted)
    }

    // Check for ambiguity resolution case after parsing new input
    if (this.inputParser.isInAmbiguousState()) {
      // TODO: I think this is now handled by the generic error case above
      // Request clarification from user to resolve ambiguity -- do not run tick(), etc.
      //println("### AMBIGUITY RESOLUTION CASE: " + statusStr)
      val score = task.goalSequence.score()
      val isCompleted = task.goalSequence.isCompleted()
      return (statusStr, score, isCompleted)
    }

    try {
      breakable {
        while (true) {
          val willActionsTakeTime: Boolean = actionHandler.doQueuedActionsTakeTime()

          // Run queued actions
          val actionOutStr = actionHandler.runQueuedActions()
          userOutStr.append(actionOutStr)

          // TODO: Also added this check for goal conditions being met BEFORE processing the tick, for cases where the tick can modify the goal state (e.g. trees growing past the desired life stage in one tick)
          //## NOTE: This might break some other things, so let's keep an eye on it for a bit with the gold agents.
          // Check whether the goal conditions are met
          task.goalSequence.tick(objMonitor, agent)

          // Run universe tick
          if (willActionsTakeTime) {
            universe.clearTickProcessedRecursive()
            universe.tick()

            // Run any simplifications that need to be run
            SimplifierProcessor.runSimplificationsEachTick(universe, agent)

            // Increment the number of iterations
            this.curIter += 1

          }

          // Check whether the goal conditions are met
          task.goalSequence.tick(objMonitor, agent)

          // If the agent is not waiting, then break.  But if the agent is waiting, continue cycling through until the agent is finished waiting X number of ticks.
          if (agent.isWaiting()) {
            agent.decrementWait()
          } else {
            break
          }
        }
      }
      //## Uncomment when debugging in IntelliJ
    } catch {
      case e: Throwable => {
        this.setErrorState(e.toString)
      }
    }


    val score = task.goalSequence.score()
    val isCompleted = task.goalSequence.isCompleted()

    // Return action string
    val outStr = userOutStr.toString().trim.replaceAll(" +", " ")
    return (outStr, score, isCompleted)
  }

}
