package language.runtime.pythonapi

import language.runtime.AgentInterface
import language.runtime.inputparser.InputParser
import language.struct.EnvObject
import py4j.GatewayServer

import scala.util.control.Breaks.{break, breakable}

class PythonInterface() {
  var agentInterface:Option[AgentInterface] = None
  var agent:Option[EnvObject] = None
  var curIter:Int = 0

  var scriptFilename:String = ""

  def load(filename:String): Unit = {
    scriptFilename = filename
    agentInterface = Some(new AgentInterface(scriptFilename))
    agent = Some(agentInterface.get.getAgent())
    curIter = 0
  }

  def reset() = {
    this.load(scriptFilename)
  }

  def shutdown(): Unit = {
    sys.exit(0)
  }



  def step(userInputString:String): String = {
    val outStr = new StringBuilder
    // Error checking
    if (agentInterface.isEmpty) return ("ERROR: Interface is not initialized -- call reset() before beginning.")
    if (agent.isEmpty) return ("ERROR: No agent is marked as main.")

    // Process step in environment
    val (success, errorStr, description) = agentInterface.get.step(userInputString, debugOutput = false)
    println("Description: ")
    println(description)

    // DEBUG
    val referents = InputParser.getPossibleReferents(agentInterface.get.getAgentVisibleObjects()._2)
    println("Possible referents: " + referents.mkString(", "))

    outStr.append(description)
    outStr.append("\nPossible referents: " + referents.mkString(", "))

    curIter += 1
    // Return
    outStr.toString()
  }


}

object PythonInterface {

  def main(args:Array[String]): Unit = {
    println ("Initializing Virtual Environment Python Server...")
    val obj = new PythonInterface()

    val server = new GatewayServer(obj)
    server.start()

  }

}
