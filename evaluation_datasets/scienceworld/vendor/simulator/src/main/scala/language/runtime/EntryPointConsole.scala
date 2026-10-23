package language.runtime

import language.model.Str
import language.runtime.inputparser.InputParser
import scala.util.control.Breaks._

/*
 * Main entry point for running a script in the console
 */
class EntryPointConsole {

}

object EntryPointConsole {

  def main(args:Array[String]) {
    //val scriptFilename = "tests/test3.env"
    //val scriptFilename = "tests/test3.scala"
    val scriptFilename = "tests/test4.scala"

    val agentInterface = new AgentInterface(scriptFilename)
    val agent = agentInterface.getAgent()

    val startTime = System.currentTimeMillis()

    breakable {
      var curIter = 0
      var userInputString:String = "look around"
      while (true) {
        println("")
        println("---------------------------------------")
        println(" Iteration " + curIter)
        println("---------------------------------------")
        println("")

        // Process step in environment
        val (success, errorStr, description) = agentInterface.step(userInputString, debugOutput = true)
        println("Description: ")
        println(description)

        // DEBUG
        val referents = InputParser.getPossibleReferents(agentInterface.getAgentVisibleObjects()._2)
        println("Possible referents: " + referents.mkString(", "))

        // Get (and process) next user action
        var validInput:Boolean = false
        while (!validInput) {
          userInputString = agentInterface.getUserInput()

          if (userInputString == "debug") {
            agentInterface.printDebugDisplay()
          } else {
            validInput = true
          }
        }

        if ((userInputString.trim.toLowerCase == "quit") || (userInputString.trim.toLowerCase == "exit")) break()
        curIter += 1
      }
    }

    val deltaTime = System.currentTimeMillis() - startTime
    println ("Total execution time: " + deltaTime + " msec")

  }

}
