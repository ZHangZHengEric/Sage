package scienceworld

import main.scala.scienceworld.runtime.SimplifierProcessor
import scienceworld.environments.EnvironmentMaker
import scienceworld.goldagent.{PathFinder, RunHistory}
import scienceworld.objects.agent.Agent
import scienceworld.objects.devices.{Freezer, Fridge, Sink, Stove}
import scienceworld.objects.location.{Location, Room, Universe}
import scienceworld.objects.portal.Door
import scienceworld.input.{ActionDefinitions, ActionHandler, InputParser}
import scienceworld.objects.substance.food.Apple
import scienceworld.properties.BlackPaintProp
import scienceworld.runtime.AgentInterface
import scienceworld.runtime.pythonapi.PythonInterface
import scienceworld.tasks.{Task, TaskMaker1}
import scienceworld.tasks.goals.ObjMonitor
import scienceworld.tasks.specifictasks.TaskChangeOfState
import scienceworld.tasks.specifictasks.TaskChangeOfState.MODE_MELT

import scala.collection.mutable.ArrayBuffer
import scala.io.StdIn.readLine
import scala.util.control.Breaks.{break, breakable}
import collection.JavaConverters._

class EntryPoint {

}

object EntryPoint {


  /*
   * Main
   */

  def main(args:Array[String]) = {
    println("Initializing... ")

    val interface = new PythonInterface()

    //val (universe, agent) = EnvironmentMaker.mkKitchenEnvironment()
    //val (universe, agent) = EnvironmentMaker.mkElectricalEnvironment()
    //println(universe.getDescription())


    val startTime = System.currentTimeMillis()

    println ("TASK LIST: ")
    val taskList = interface.getTaskNames().asScala
    for (i <- 0 until taskList.size) {
      val taskName = taskList(i)
      val numVariations = interface.getTaskMaxVariations(taskName)
      println( i.formatted("%5s") + ": \t" + taskName.formatted("%60s") + "  (" + numVariations + " variations)")
    }


    // Pick a task
    //val taskName = taskMaker.getTaskList()(6)
    //val taskName = taskMaker.getTaskList()(8)
    //val taskName = taskMaker.getTaskList()(7)
    //val taskName = taskMaker.getTaskList()(0)

    //val taskName = taskMaker.getTaskList()(5)
    //val taskName = taskMaker.getTaskList()(13)
    val taskName = interface.getTaskNames().asScala(4)

    //val simplificationStr = "teleportAction,noElectricalAction,openDoors,selfWateringFlowerPots"
    //val simplificationStr = "teleportAction,openDoors,selfWateringFlowerPots"   // with Electrical actions
    val simplificationStr = "easy"

    //val simplificationStr = ""

    // Load task
    interface.load(taskName, variationIdx = 1, simplificationStr)

    println ("Task: " + interface.getTaskDescription() )

    // Simplifications
    println ("Possible simplifications: " + SimplifierProcessor.getPossibleSimplifications())

    // DEBUG: Set the task/goals
    var curIter:Int = 0

    breakable {
      var userInputString:String = "look around"
      while (true) {
        curIter = interface.getNumMoves()
        println("")
        println("---------------------------------------")
        println(" Iteration " + curIter)
        println("---------------------------------------")
        println("")

        // Process step in environment
        //val (description, score, isCompleted) = agentInterface.step(userInputString)
        val description = interface.step(userInputString)
        val score = interface.getScore()
        val isCompleted = interface.isComplete

        println("")
        println("Description: ")
        println(description)

        println("")
        //println("metal pot: " + metalPot.propMaterial.get.temperatureC)
        //println("water: " + water.propMaterial.get.temperatureC)

        println("Score: " + score.formatted("%3.3f"))
        println("IsCompleted: " + isCompleted)


        // DEBUG
        //val referents = agentInterface.inputParser.getAllReferents(agentInterface.getAgentVisibleObjects()._2)

        val referents = InputParser.getAllUniqueReferents(interface.agentInterface.get.getAgentVisibleObjects()._2, includeHidden = true).map(_._1)
        println("Possible referents: " + referents.mkString(", "))

        val validActions = interface.agentInterface.get.getValidActionObjectCombinations().sorted.toList
        println("Possible actions: " + validActions.mkString(", "))
        println("Possible actions: " + interface.agentInterface.get.getPossibleActionsWithIDsJSON() )
        println("Valid actions: " + interface.agentInterface.get.getValidActionObjectCombinationsJSON() )

        println("Goal sequence progress: \n" + interface.agentInterface.get.getGoalProgressStr() )

        println("Referents: " + interface.agentInterface.get.getAllObjectIdsTypesReferentsLUTJSON() )

        //println("Locations: " + PathFinder.buildLocationGraph(universe) )

        //println("Pathfinder test: " + PathFinder.getLocationSequence(universe, startLocation = "living room", endLocation = "foundry")._2.mkString(", "))
        /*
        println("Pathfinder test: ")
        val path = PathFinder.createActionSequenceSearchPattern(universe = interface.agentInterface.get.universe, agent = interface.agentInterface.get.agent, startLocation = interface.agentInterface.get.agent.getContainer().get.name)
        for (elem <- path) {
          println("\t" + elem.mkString(", "))
        }
         */

        //println("Possible actions:\n\t" + actionHandler.getActionExamplesPlainText().mkString("\n\t"))
        //println("Possible Combinations:\n\t" + agentInterface.getPossibleActionObjectCombinations().mkString("\n\t") )

        /*
        println("TEST: ")
        println(agentInterface.getAllObjectIdsTypesReferentsLUTJSON())
        println("")
         */

        // Get (and process) next user action
        var validInput:Boolean = false
        while (!validInput) {
          userInputString = interface.agentInterface.get.getUserInput()

          if (userInputString == "debug") {
            //agentInterface.printDebugDisplay()
          } else if (userInputString == "help") {
            println("Possible Actions: \n" + interface.agentInterface.get.getPossibleActions().mkString("\n"))
          } else if (userInputString == "validactions") {
            // Collect all objects visible to the agent
            val visibleObjTreeRoot = interface.agentInterface.get.getAgentVisibleObjects()._2
            val agentInventory = interface.agentInterface.get.agent.getInventoryContainer()
            val allVisibleObjects = InputParser.collectObjects(visibleObjTreeRoot, includeHidden = false).toList ++ InputParser.collectObjects(agentInventory, includeHidden = false).toList
            // Collect UUID -> Unique Referent LUT
            val uuid2referentLUT = interface.agentInterface.get.inputParser.getAllUniqueReferentsLUT(visibleObjTreeRoot, includeHidden = false)

            // Generate all possible valid actions
            val validActions = interface.agentInterface.get.getValidActionObjectCombinations() // ActionDefinitions.mkPossibleActions(agent, allVisibleObjects.toArray, uuid2referentLUT)

            println("Valid actions (length = " + validActions.length + ")")
            for (i <- 0 until validActions.length) {
              println(i + ": \t" + validActions(i).toString())
            }
          } else if (userInputString == "history") {
            println("History:")
            println(interface.currentHistory.historyActions.mkString("\n"))
          } else {
            validInput = true
          }
        }

        if ((userInputString.trim.toLowerCase == "quit") || (userInputString.trim.toLowerCase == "exit")) break()

      }
    }

    val deltaTime = System.currentTimeMillis() - startTime
    println("Total execution time: " + deltaTime + " msec for " + curIter + " iterations (" + (curIter / (deltaTime.toDouble/1000.0f)) + " iterations/sec)")

    println ("")
    println ("Exiting...")

  }

}
