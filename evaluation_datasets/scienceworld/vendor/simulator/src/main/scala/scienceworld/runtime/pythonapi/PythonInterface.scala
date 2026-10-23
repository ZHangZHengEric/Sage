package scienceworld.runtime.pythonapi

import java.io.{File, FileOutputStream,PrintWriter}

import main.scala.scienceworld.runtime.SimplifierProcessor
import scienceworld.environments.EnvironmentMaker
import scienceworld.goldagent.RunHistory
import scienceworld.input.{ActionDefinitions, InputParser}
import scienceworld.objects.agent.Agent
import scienceworld.runtime.AgentInterface
import scienceworld.struct.EnvObject
import scienceworld.tasks.{Task, TaskMaker1}
import util.{UniqueIdentifier, UniqueTypeID}
import py4j.GatewayServer

import collection.JavaConverters._
import scala.util.Random
import scala.util.control.Breaks.{break, breakable}


// Storage class
class PythonInterfaceReturn(val observation:String, val score:Double, val isCompleted:Boolean) {

}

class PythonInterface() {
  val ERROR_MESSAGE_UNINITIALIZED = "ERROR: Interface is not initialized -- call reset() before beginning."

  var agentInterface:Option[AgentInterface] = None
  var agent:Option[Agent] = None
  val actionHandler = ActionDefinitions.mkActionDefinitions()

  var taskStr:String = ""                // Environment/task name
  var taskVariationIdx:Int = 0           // Task variation seed
  var simplificationStr:String = ""      // CSV delimited string of simplifications to perform to the environment

  var goldActionsStr = Array.empty[String]    // Sequence of gold actions for this task
  var goldPathGenerationEnabled:Boolean = false

  var score:Double = 0.0
  var isComplete:Boolean = false

  var errorUnknownEnvironment:Boolean = false
  var errorStr:String = ""

  var taskMaker = new TaskMaker1()

  var currentHistory = new RunHistory("", -1, -1)


  /*
   * Load/reset/shutdown server
   */
  def load(taskStr:String, variationIdx:Int, simplificationStr:String, generateGoldPath:Boolean = false): String = {
    var goldActionSequence = Array.empty[String]

    if (generateGoldPath) {
      // First, reset environment to new specifications
      doLoad(taskStr, variationIdx, simplificationStr)

      println("* Generating Gold Path")
      // Then, compute gold path
      val (goldPath, success) = taskMaker.createGoldActions(taskStr, variationIdx, this)
      println("* Completed Generating Gold Path")
      println("* Gold path (length = " + goldPath.length + " actions):")
      println("----")
      println(goldPath.mkString("\n"))
      println("----")

      println("this.goldActionStr:")
      println(this.goldActionsStr.mkString("\n"))

      // Store gold action sequence
      goldActionSequence = goldPath
      this.goldPathGenerationEnabled = generateGoldPath

    } else {
      goldActionsStr = Array.empty[String]
    }

    // Then, reset environment again
    doLoad(taskStr, variationIdx, simplificationStr)

    // Store gold action sequence, since 'doLoad' clears it
    if (generateGoldPath == true) {
      this.goldActionsStr = goldActionSequence
    }

    return this.errorStr

  }

  def reset() = {
    this.load(this.taskStr, this.taskVariationIdx, this.simplificationStr, generateGoldPath = this.goldPathGenerationEnabled)
  }


  private def doLoad(taskStr:String, variationIdx:Int, simplificationStr:String): Unit = {
    this.taskStr = taskStr
    this.taskVariationIdx = variationIdx
    this.simplificationStr = simplificationStr

    // Clear error string
    this.errorStr = ""

    // Reset UUID counter
    UniqueIdentifier.reset()

    //## TEST: Reset Task Maker (and thus recreate all possible task objects)
    Random.setSeed(variationIdx)
    taskMaker = new TaskMaker1()

    // Make environment and agent
    Random.setSeed(variationIdx)
    val (universe, agent_) = EnvironmentMaker.mkKitchenEnvironment(seed = variationIdx)

    // Set up task
    val (task_, taskErrStr) = taskMaker.doTaskSetup(taskStr, this.taskVariationIdx, universe, agent_)
    var task:Option[Task] = None
    if (task_.isDefined) {
      task = task_
    } else {
      task = Some( Task.mkUnaccomplishableTask() )
      errorStr += "ERROR: Task (" + this.taskStr + "): " + taskErrStr
    }

    // Populated separately
    goldActionsStr = Array.empty[String]

    if (task.isDefined) {
      this.errorUnknownEnvironment = false
      agent = Some(agent_)
      agentInterface = Some(new AgentInterface(universe, agent.get, task.get, simplificationStr))

      // Reset run history
      val taskIdx = this.getTaskNames().indexOf(taskStr)
      currentHistory = new RunHistory(taskStr, taskIdx, variationIdx, getTaskDescription(), simplificationStr)

    } else {
      this.errorUnknownEnvironment = true
      agentInterface = None
      currentHistory = new RunHistory("", -1, -1, "")
    }

  }


  def shutdown(): Unit = {
    sys.exit(0)
  }

  /*
   * Get valid tasks/environments
   */
  def getTaskNames():java.util.List[String] = {
    taskMaker.getTaskList().toList.asJava
  }

  // Get the maximum variations for a given task
  def getTaskMaxVariations(taskName:String): Int = {
    taskMaker.getMaxVariations(taskName)
  }


  /*
   * Train/development/test sets
   */

  // Split into train/dev/test sets (using a 50%/25%/25% split).
  // TODO: Make private, so access can only be from functions below?
  def getSets():(List[Int], List[Int], List[Int]) = {
    val maxVariations = this.getTaskMaxVariations(taskName = this.taskStr)
    // Special cases with small numbers of variations
    if (maxVariations == 0) return (List.empty[Int], List.empty[Int], List.empty[Int])
    if (maxVariations == 1) return (List(0), List.empty[Int], List(0))
    if (maxVariations == 2) return (List(0), List.empty[Int], List(1))
    if (maxVariations == 3) return (List(0), List(1), List(2))
    if (maxVariations == 4) return (List(0, 1), List(2), List(3))


    // General case
    val indices = Range(0, maxVariations).toList
    val groupSize = math.floor(indices.length / 4).toInt
    val groups = indices.grouped(groupSize).toList

    // Split into train/dev/test groups
    val train = groups(0) ++ groups(1)
    val dev = groups(2)
    var test = groups(3)
    if (groups.length > 4) test = groups(3) ++ groups(4)

    return (train, dev, test)
  }

  def getVariationsTrain():java.util.List[Int] = {
    val (train, dev, test) = this.getSets()
    return train.asJava
  }

  def getVariationsDev():java.util.List[Int] = {
    val (train, dev, test) = this.getSets()
    return dev.asJava
  }

  def getVariationsTest():java.util.List[Int] = {
    val (train, dev, test) = this.getSets()
    return test.asJava
  }

  def getRandomVariationTrain():Int = {
    val (train, dev, test) = this.getSets()
    val randIdx = scala.util.Random.nextInt(train.length)
    return train(randIdx)
  }

  def getRandomVariationDev():Int = {
    val (train, dev, test) = this.getSets()
    val randIdx = scala.util.Random.nextInt(dev.length)
    return dev(randIdx)
  }

  def getRandomVariationTest():Int = {
    val (train, dev, test) = this.getSets()
    val randIdx = scala.util.Random.nextInt(test.length)
    return test(randIdx)
  }


  /*
   * Simplifications
   */
  def getSimplificationsUsed():String = {
    return SimplifierProcessor.getSimplificationsUsed()
  }

  def getPossibleSimplifications():String = {
    return SimplifierProcessor.getPossibleSimplifications()
  }


  /*
   * Gold action sequence
   */
  def getGoldActionSequence():java.util.List[String] = {
    return this.goldActionsStr.toList.asJava
  }

  /*
   * History
   */
  def getActionHistory():java.util.List[String] = {
    return this.currentHistory.historyActions.toList.asJava
  }

  // Get entire run history for this instance in JSON format
  def getRunHistoryJSON():String = {
    return this.currentHistory.toJSON()
  }


  /*
   * Get object/action space
   */
  def getPossibleActions(): java.util.List[String] = {
    if (!agentInterface.isDefined) return List(ERROR_MESSAGE_UNINITIALIZED).asJava
    agentInterface.get.getPossibleActions().toList.asJava
  }

  def getPossibleActionsWithIDs(): String = {
    if (!agentInterface.isDefined) return ERROR_MESSAGE_UNINITIALIZED
    agentInterface.get.getPossibleActionsWithIDsJSON()
  }

  def getPossibleObjects(): java.util.List[String] = {
    if (!agentInterface.isDefined) return List(ERROR_MESSAGE_UNINITIALIZED).asJava
    agentInterface.get.getPossibleObjects().toList.asJava
  }

  def getPossibleObjectReferentLUTJSON():String = {
    if (!agentInterface.isDefined) return ERROR_MESSAGE_UNINITIALIZED
    agentInterface.get.getPossibleObjectReferentLUTJSON()
  }

  def getPossibleObjectReferentTypesLUTJSON():String = {
    if (!agentInterface.isDefined) return ERROR_MESSAGE_UNINITIALIZED
    agentInterface.get.getPossibleObjectReferentTypesLUTJSON()
  }

  def getValidActionObjectCombinations():java.util.List[String] = {
    if (!agentInterface.isDefined) return List(ERROR_MESSAGE_UNINITIALIZED).asJava
    agentInterface.get.getValidActionObjectCombinations().toList.sorted.asJava
  }

  def getValidActionObjectCombinationsJSON():String = {
    if (!agentInterface.isDefined) return ERROR_MESSAGE_UNINITIALIZED
    agentInterface.get.getValidActionObjectCombinationsJSON()
  }

  def getPossibleActionObjectCombinationsJSON(): String = {
    if (!agentInterface.isDefined) return ERROR_MESSAGE_UNINITIALIZED
    agentInterface.get.getPossibleActionObjectCombinationsJSON()
  }

  def getObjectTypesLUTJSON(): String = {
    UniqueTypeID.toJSON()
  }

  def getAllObjectTypesLUTJSON(): String = {
    if (!agentInterface.isDefined) return ERROR_MESSAGE_UNINITIALIZED
    agentInterface.get.getAllObjectTypesLUTJSON()
  }

  def getAllObjectIdsTypesReferentsLUTJSON(): String = {
    if (!agentInterface.isDefined) return ERROR_MESSAGE_UNINITIALIZED
    agentInterface.get.getAllObjectIdsTypesReferentsLUTJSON()
  }

  def getNumMoves():Integer = {
    if (agentInterface.isEmpty) return 0
    agentInterface.get.getCurIterations()
  }

  def getTaskDescription():String = {
    if (agentInterface.isEmpty) return ERROR_MESSAGE_UNINITIALIZED
    agentInterface.get.getTaskDescription()
  }

  def getObjectTree(folderPath:String = ""):String = {
    if (agentInterface.isEmpty) return ERROR_MESSAGE_UNINITIALIZED

    val objTree = agentInterface.get.universe.toJSON()
    if (folderPath == "") return objTree

    var pw = new PrintWriter(folderPath + "/objectTree.json");
    pw.print(objTree)
    pw.close()
    return ""
  }

  /*
   * Take action steps and get observations/scores
   */

  def getScore():Double = this.score

  def getGoalProgressStr():String = agentInterface.get.getGoalProgressStr()

  def getCompleted():Boolean = this.isComplete

  // Normal
  def step(userInputString:String): String = {
    val outStr = new StringBuilder
    // Error checking
    if (this.errorStr != "") return this.errorStr
    if (this.errorUnknownEnvironment) return "ERROR: Unknown task (" + this.taskStr + ") or task variation index (" + this.taskVariationIdx + ")."
    if (agentInterface.isEmpty) return ERROR_MESSAGE_UNINITIALIZED
    if (agent.isEmpty) return "ERROR: No agent is marked as main."
    if (agent.get.getContainer().isEmpty) return "ERROR: Agent is not in a container."

    // Get agent's container (to render agent's perspective)
    val agentContainer = agent.get.getContainer().get

    // Process special input commands (help, objects)
    if (userInputString.trim.toLowerCase == "help") {
      return "Possible actions: \n\t" + this.getPossibleActions().toArray().mkString("\n\t")
    }
    if (userInputString.trim.toLowerCase == "objects") {
      return "Possible object references: \n\t" + this.getPossibleObjects().toArray().mkString("\n\t")
    }
    if (userInputString.trim.toLowerCase == "task") {
      return "Task description:\n" + agentInterface.get.getTaskDescription()
    }

    // For history: record free look and inventory before step is taken
    val freelookStr = this.freeActionLook()
    val inventoryStr = this.freeActionInventory()

    // Process step in environment
    val (description, score_, isCompleted_) = agentInterface.get.step(userInputString)
    this.score = score_
    this.isComplete = isCompleted_

    // Store in history
    currentHistory.addStep(userInputString, (description, score_, isCompleted_), freelookStr, inventoryStr)

    println("Description: ")
    println(description)

    // DEBUG
    val referents = InputParser.getPossibleReferents(agentInterface.get.getAgentVisibleObjects()._2, agentContainer)
    println("Possible referents: " + referents.mkString(", "))

    if (description.length > 0) {
      outStr.append(description)
    } else {
      outStr.append("Unknown action.  Type 'help' for a list of actions, and 'objects' for a list of possible object referents. ")
    }
    //outStr.append("\nPossible referents: " + referents.mkString(", "))

    println ("step() finished.")

    // Return
    return outStr.toString()
  }

  // Free actions
  def freeActionLook():String = {
    // Error checking
    if (this.errorStr != "") return this.errorStr
    if (this.errorUnknownEnvironment) return "ERROR: Unknown task (" + this.taskStr + ") or task variation index (" + this.taskVariationIdx + ")."
    if (agentInterface.isEmpty) return ERROR_MESSAGE_UNINITIALIZED
    if (agent.isEmpty) return "ERROR: No agent is marked as main."
    if (agent.get.getContainer().isEmpty) return "ERROR: Agent is not in a container."

    return agentInterface.get.freeActionLook()
  }

  def freeActionInventory():String = {
    // Error checking
    if (this.errorStr != "") return this.errorStr
    if (this.errorUnknownEnvironment) return "ERROR: Unknown task (" + this.taskStr + ") or task variation index (" + this.taskVariationIdx + ")."
    if (agentInterface.isEmpty) return ERROR_MESSAGE_UNINITIALIZED
    if (agent.isEmpty) return "ERROR: No agent is marked as main."
    if (agent.get.getContainer().isEmpty) return "ERROR: Agent is not in a container."

    return agentInterface.get.freeActionInventory()
  }

  def freeActionTaskDesc():String = {
    // Error checking
    if (this.errorStr != "") return this.errorStr
    if (this.errorUnknownEnvironment) return "ERROR: Unknown task (" + this.taskStr + ") or task variation index (" + this.taskVariationIdx + ")."
    if (agentInterface.isEmpty) return ERROR_MESSAGE_UNINITIALIZED
    if (agent.isEmpty) return "ERROR: No agent is marked as main."
    if (agent.get.getContainer().isEmpty) return "ERROR: Agent is not in a container."

    return agentInterface.get.freeActionTaskDesc()
  }


}

object PythonInterface {

  def printUsage(): Unit = {
    println("Usage: PythonInterface <portNumber>")
  }

  def main(args:Array[String]): Unit = {
    println ("Initializing Virtual Environment Python Server...")
    val obj = new PythonInterface()

    // Parse command line argument for port
    var port:Int = 25335      // Default port (if not specified)
    if (args.length == 1) {
      try {
        port = args(0).toInt
      } catch {
        case e:Throwable => {
          printUsage()
          throw new RuntimeException("ERROR: Unable to parse port number into integer(" + args(0) + ").")
        }
      }
    } else if (args.length > 1) {
      printUsage()
      sys.exit(1)
    }

    println ("Starting server on port " + port + ".")

    val server = new GatewayServer(obj, port)
    server.start()

    println ("Server started... ")

  }

}
