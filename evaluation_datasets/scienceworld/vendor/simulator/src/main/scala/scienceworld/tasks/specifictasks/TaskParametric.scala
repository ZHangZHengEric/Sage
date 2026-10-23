package scienceworld.tasks.specifictasks

import scienceworld.actions.Action
import scienceworld.objects.agent.Agent
import scienceworld.runtime.pythonapi.PythonInterface
import scienceworld.struct.EnvObject
import scienceworld.tasks.{Task, TaskModifier, TaskValueBool, TaskValueDouble, TaskValueInt, TaskValueStr}

import collection.JavaConverters._

trait TaskParametric {
  val taskName:String

  def numCombinations():Int
  def getCombination(idx:Int):Array[TaskModifier]

  //def setupCombination(modifiers:Array[TaskModifier], universe:EnvObject, agent:Agent)
  def setupCombination(combinationNum:Int, universe:EnvObject, agent:Agent): (Boolean, String)

  def setupGoals(combinationNum:Int): Task

  def mkGoldActionSequence(modifiers:Array[TaskModifier], runner:PythonInterface): (Boolean, Array[String])

  /*
   * Helpers
   */

  // Search the TaskModifiers for a TaskValueStr (key/value pair), that might include additional info (such as the answer) to supply to the goal conditions.
  def getTaskValueStr(modifiers:Array[TaskModifier], key:String):Option[String] = {
    // TODO
    for (mod <- modifiers) {
      mod match {
        case m:TaskValueStr => {
          if (m.key == key) return Some(m.value)
        }
        case _ => { }
      }
    }
    // If we reach here, the key wasn't found
    return None
  }

  def getTaskValueBool(modifiers:Array[TaskModifier], key:String):Option[Boolean] = {
    // TODO
    for (mod <- modifiers) {
      mod match {
        case m:TaskValueBool => {
          if (m.key == key) return Some(m.value)
        }
        case _ => { }
      }
    }
    // If we reach here, the key wasn't found
    return None
  }

  def getTaskValueDouble(modifiers:Array[TaskModifier], key:String):Option[Double] = {
    // TODO
    for (mod <- modifiers) {
      mod match {
        case m:TaskValueDouble => {
          if (m.key == key) return Some(m.value)
        }
        case _ => { }
      }
    }
    // If we reach here, the key wasn't found
    return None
  }

  def getTaskValueInt(modifiers:Array[TaskModifier], key:String):Option[Int] = {
    // TODO
    for (mod <- modifiers) {
      mod match {
        case m:TaskValueInt => {
          if (m.key == key) return Some(m.value)
        }
        case _ => { }
      }
    }
    // If we reach here, the key wasn't found
    return None
  }

  /*
   * Helper functions (runner for gold action sequences)
   */

  // Run a series of actions in the environment (typically for creating a gold path)
  def runActionSequence(actionSequence:Array[String], runner:PythonInterface): Unit = {
    for (actionStr <- actionSequence) {
      this.runAction(actionStr, runner)
    }
  }

  def runAction(actionStr:String, runner:PythonInterface): Unit = {
    TaskParametric.runAction(actionStr, runner)
  }

  def getActionHistory(runner:PythonInterface):Array[String] = {
    TaskParametric.getActionHistory(runner)
  }

  def getCurrentAgentLocation(runner:PythonInterface):EnvObject = {
    TaskParametric.getCurrentAgentLocation(runner)
  }

}


object TaskParametric {

  /*
   * Helper functions (runner for gold action sequences)
   */
  def runAction(actionStr:String, runner:PythonInterface): Unit = {
    println(">>> " + actionStr)
    val observation = runner.step(actionStr)
    println("OBS: " + observation)
    println("")

    // Check for ambiguous state -- if it happens, automatically pick the first possible resolution.
    if (runner.agentInterface.get.inputParser.isInAmbiguousState()) {
      // If in an ambiguous state, then select the first option
      this.runAction("0", runner)
    } /*else {
      if (observation.contains("Ambiguous")) {
        runner.currentHistory.addStep("not in ambiguous state BUT OBSERVATION CONTAINS AMBIGUOUS", ("", 0, false))
      }
      runner.currentHistory.addStep("not in ambiguous state", ("", 0, false))
    }
    */

  }

  def getActionHistory(runner:PythonInterface):Array[String] = {
    return runner.getActionHistory().asScala.toArray
  }

  def getCurrentAgentLocation(runner:PythonInterface):EnvObject = {
    return runner.agentInterface.get.agent.getContainer().get
  }

}
