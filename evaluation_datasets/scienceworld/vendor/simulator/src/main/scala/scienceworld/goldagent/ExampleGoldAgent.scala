package scienceworld.goldagent
import java.io.PrintWriter

import main.scala.scienceworld.runtime.SimplifierProcessor
import scienceworld.runtime.pythonapi.PythonInterface

import scala.collection.JavaConverters._
import scala.collection.mutable.ArrayBuffer
import scala.util.control.Breaks._
import scala.util.Random


object ExampleGoldAgent {


  def main(args:Array[String]) = {
    val interface = new PythonInterface()

    //val specificTasks = Array(25,26,27)           // Do specific tasks
    //val specificTasks = Array(7,8,9,10)           // Do specific tasks
    //val specificTasks = Array(15,16)           // Do specific tasks
    //val specificTasks = Array(28,29)           // Do specific tasks
    //val specificTasks = Array(4,5,6,7)           // Do specific tasks
    val specificTasks = Array(0,1,2,3,4,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29)           // Do specific tasks
    //val specificTasks = Array(9, 10)           // Do specific tasks
    //val specificTasks = Array(18)           // Do specific tasks
    //val specificTasks = Array(14)           // Do specific tasks

    //val specificTasks = Array(0,1,2,3)         // Do specific tasks
    //val specificTasks = Array(4,5,6)           // Do specific tasks
    //val specificTasks = Array(7,8,9,10)        // Do specific tasks
    //val specificTasks = Array(11,12,13,14)     // Do specific tasks
    //val specificTasks = Array(15,16)           // Do specific tasks
    //val specificTasks = Array(17,18,19)        // Do specific tasks
    //val specificTasks = Array(20,21,22)        // Do specific tasks
    //val specificTasks = Array(23,24)           // Do specific tasks
    //val specificTasks = Array(25,26,27)        // Do specific tasks
    //val specificTasks = Array(28,29)           // Do specific tasks
    //val specificTasks = Array(17)           // Do specific tasks

    //val specificTasks = Array.empty[Int]      // Do all

    val exportFilename = "goldsequences-" + specificTasks.mkString("-") + ".json"

    val simplificationStr = "easy"

    val errors = new ArrayBuffer[String]
    var numVariationsTested:Int = 0

    val errorHistories = new ArrayBuffer[RunHistory]

    // Array storing all action sequences
    val goldActionSequences = new ArrayBuffer[RunHistory]

    // Create environment
    // Get a task name
    val taskNames = interface.getTaskNames().asScala.toList


    println ("TASK LIST: ")
    val taskList = interface.taskMaker.getTaskList()
    for (i <- 0 until taskList.length) {
      val taskName = taskList(i)
      val numVariations = interface.taskMaker.getMaxVariations(taskName)
      println( i.formatted("%5s") + ": \t" + taskName.formatted("%60s") + "  (" + numVariations + " variations)")
    }

    val taskScores = new ArrayBuffer[ Array[Double] ]()
    for (taskIdx <- 0 until taskNames.length) {
      breakable {
        val taskName = taskNames(taskIdx)
        // If we've specified specific tasks to run, skip this one
        if ((!specificTasks.isEmpty) && (!specificTasks.contains(taskIdx))) {
          taskScores.append(Array.empty[Double])
          break
        }


        // Simulation parameters
        var curEpisode: Int = 0

        var totalSteps: Long = 0

        var userInput = "look around"
        val episodeScores = new ArrayBuffer[Double]
        val maxTaskVariations = interface.getTaskMaxVariations(taskName)



        // For each variation
        var subsampleEveryNth:Int = 1
        //var subsampleEveryNth:Int = 8
        for (variationIdx <- 0 until maxTaskVariations) {
        //for (variationIdx <- 0 until math.min(20, maxTaskVariations)) {
          if (variationIdx % subsampleEveryNth == 0) {
            println("---------------------------")
            println("   Task " + taskIdx + "   " + taskName)
            println("   Variation: " + variationIdx + " / " + maxTaskVariations)
            println("---------------------------")

            // Load the task/variation
            interface.load(taskName, variationIdx, simplificationStr, generateGoldPath = true)

            // Get reference to AgentInterface
            val agentInterface = interface.agentInterface

            println("Task Description: " + agentInterface.get.getTaskDescription())

            // Get the gold action sequence
            val goldActionSeq = interface.getGoldActionSequence().asScala.toArray

            // Create a history object to store this run
            var foldDesc = "train"
            if (interface.getVariationsDev().asScala.toArray.contains(variationIdx)) foldDesc = "dev"
            if (interface.getVariationsTest().asScala.toArray.contains(variationIdx)) foldDesc = "test"
            val history = new RunHistory(taskName, taskIdx, variationIdx, taskDescription = agentInterface.get.getTaskDescription(), simplificationStr = simplificationStr, foldDesc = foldDesc)

            // Run a free initial 'look' action, and add it to the history?
            val initialFl = interface.freeActionLook()
            val initialInv = interface.freeActionInventory()
            val initialObs = agentInterface.get.step("look around")
            history.addStep("look around", initialObs, initialFl, initialInv)


            var curScore: Double = 0.0
            for (actionIdx <- 0 until goldActionSeq.length) {
              // Get next gold action
              userInput = goldActionSeq(actionIdx)

              // Record free look and inventory before step is taken
              val freelookStr = interface.freeActionLook()
              val inventoryStr = interface.freeActionInventory()

              // Supply action to environment, get next environment observation
              println(">> " + userInput)
              val observation = agentInterface.get.step(userInput)
              curScore = observation._2
              println("Observation: ")
              println(observation)

              // Store in history
              history.addStep(userInput, observation, freelookStr, inventoryStr)

              // Check for error state:
              if (agentInterface.get.isInErrorState()) {

                println("Action History:")
                for (i <- 0 to actionIdx) {
                  println(i + ": \t" + goldActionSeq(i))
                }
                println("")
                println("ERROR STATE DETECTED!")
                println("ERROR MESSAGE: ")
                println(agentInterface.get.getErrorStateMessage())

                sys.exit(1)
              }

              totalSteps += 1
            }

            // Add the goal summary to the history notes
            history.addNote(agentInterface.get.getGoalProgressStr())

            // If we reach here, we're done with the gold action sequence.  Test to make sure the score is perfect
            if (curScore < 1.0) {
              val errStr = "ERROR: Score not 100% after running gold action sequence (Task: " + taskName + ", VariationIdx: " + variationIdx + ", Score: " + curScore + ")"
              println(errStr)
              errors.append(errStr)
              println("Gold sequence: " + goldActionSeq.mkString(", "))

              errorHistories.append(history)
            }
            episodeScores.append(curScore)
            numVariationsTested += 1

            // Store action sequence
            goldActionSequences.append(history)
          }
        }
        taskScores.append(episodeScores.toArray)


        // Show error histories
        println ("ERROR HISTORIES:")
        for (history <- errorHistories) {
          println(history.toString())
        }

        // Show summary statistics
        println("")
        println("---------------------------------")
        println("Scores:")
        println("Simplifications: " + SimplifierProcessor.getSimplificationsUsed())
        println("---------------------------------")
        println("Total number of variations tested: " + numVariationsTested )
        println("Total number of variations with errors in gold path: " + errors.length)
        println("---------------------------------")

        for (taskIdx <- 0 until taskScores.length) {
          val taskName = taskNames(taskIdx)
          println(taskIdx.formatted("%3s") + ": " + taskName.formatted("%60s") + "\t" + summaryStatistics(taskScores(taskIdx)))
        }

        println("---------------------------------")
      }
    }
    println ("Exporting gold action sequences...")

    this.exportGoldActionSequencesJSON(goldActionSequences, exportFilename)


    println ("Completed...")

  }


  def summaryStatistics(in:Array[Double]):String = {
    val os = new StringBuilder
    if (in.length == 0) return "no samples"

    var min:Double = in(0)
    var max:Double = in(0)
    var avg:Double = 0.0

    for (elem <- in) {
      if (elem < min) min = elem
      if (elem > max) max = elem

      // NOTE: Not including negative scores in the average
      if (elem >= 0.0) {
        avg += elem
      }

    }

    avg = avg / in.length.toDouble

    os.append("min: " + min.formatted("%3.2f").formatted("%5s") + "      ")
    os.append("max: " + max.formatted("%3.2f").formatted("%5s") + "      ")
    os.append("avg: " + avg.formatted("%3.2f").formatted("%5s") + "      ")

    return os.toString()
  }


  // Export gold action sequences to JSON file
  def exportGoldActionSequencesJSON(goldActionSequences:ArrayBuffer[RunHistory], filenameOut:String): Unit = {
    println ("Exporting gold action sequences... (" + filenameOut + ")")
    // Open file
    val pw = new PrintWriter(filenameOut)

    // Get a list of task indices
    val taskIdxs = goldActionSequences.map(_.taskIdx).toSet.toArray.sorted

    val taskJson = new ArrayBuffer[String]
    for (taskIdx <- taskIdxs) {
      val elems = new ArrayBuffer[String]
      val variations = goldActionSequences.filter(_.taskIdx == taskIdx).sortBy(_.variationIdx)
      println(" * Task " + taskIdx + " (variations: " + variations.length)

      if (variations.length > 0) {
        for (variation <- variations) {
          elems.append("\t{\"variationIdx\": " + variation.variationIdx + ", \"fold\":\"" + variation.foldDesc + "\", \"taskDescription\":\"" + RunHistory.sanitizeJSON(variation.taskDescription) + "\", \"path\": \n" + variation.toJSONArray(2) + "}")
        }

        val jsonOut = new StringBuilder()
        jsonOut.append("\"" + taskIdx + "\": {")
        jsonOut.append("\"taskIdx\": " + taskIdx + ", ")
        jsonOut.append("\"taskName\": \"" + variations(0).taskName + "\", ")
        jsonOut.append("\"goldActionSequences\": [\n")
        jsonOut.append(elems.mkString(", \n"))
        jsonOut.append("]} ")

        taskJson.append(jsonOut.toString())
      }

    }

    // Export to file
    pw.print("{" + taskJson.mkString(", \n") + "}")
    pw.flush()

    // Close file
    pw.close()

  }

}


// Storage class for histories
class RunHistory(val taskName:String, val taskIdx:Int, val variationIdx:Int, val taskDescription:String = "", val simplificationStr:String = "", val foldDesc:String = "") {
  val historyActions = new ArrayBuffer[String]
  val historyObservations = new ArrayBuffer[(String, Double, Boolean)]
  val historyFreeLook = new ArrayBuffer[String]
  val historyInventory = new ArrayBuffer[String]
  val notes = new ArrayBuffer[String]

  def length:Int = this.historyActions.length

  def addStep(action:String, observation:(String, Double, Boolean), freeLookStr:String, inventoryStr:String): Unit = {
    historyActions.append(action)
    historyObservations.append(observation)
    historyFreeLook.append(freeLookStr)
    historyInventory.append(inventoryStr)
  }

  def addNote(strIn:String): Unit = {
    notes.append(strIn)
  }

  /*
   * String methods
   */

  // Convert the history to JSON
  def toJSONArray(indentLevel:Int = 0):String = {

    val points = new ArrayBuffer[String]
    for (i <- 0 until this.length) {
      val action = historyActions(i)
      val obs = historyObservations(i)._1
      val score = historyObservations(i)._2
      val isCompleted = historyObservations(i)._3
      val freelook = historyFreeLook(i)
      val inventory = historyInventory(i)

      val json = new StringBuilder
      json.append("{")
      json.append("\"action\":\"" + RunHistory.sanitizeJSON(action) + "\", ")
      json.append("\"observation\":\"" + RunHistory.sanitizeJSON(obs) + "\", ")
      json.append("\"score\":\"" + score + "\", ")
      json.append("\"isCompleted\":\"" + isCompleted + "\", ")
      json.append("\"freelook\":\"" + RunHistory.sanitizeJSON(freelook) + "\", ")
      json.append("\"inventory\":\"" + RunHistory.sanitizeJSON(inventory) + "\"")
      json.append("}")

      points.append( json.toString())
    }

    val jsonOut = ("\t" * indentLevel) + "[" + points.mkString(",\n" + ("\t" * indentLevel)) + "]"

    return jsonOut
  }

  // More complete than above
  def toJSON(indentLevel:Int = 0):String = {
    val json = new StringBuilder
    json.append("{")
    json.append("\"taskIdx\":\"" + taskIdx + "\", ")
    json.append("\"taskName\":\"" + taskName + "\", ")
    json.append("\"variationIdx\":\"" + variationIdx + "\", ")
    json.append("\"taskDescription\":\"" + RunHistory.sanitizeJSON(taskDescription) + "\", ")
    json.append("\"simplifications\":\"" + RunHistory.sanitizeJSON(simplificationStr) + "\", ")
    json.append("\"history\":" + this.toJSONArray()+ " ")
    json.append("}")

    return json.toString
  }

  override def toString():String = {
    val os = new StringBuilder

    os.append("\n------------------------------------------------------------------------\n\n")
    os.append("Task: " + taskName + "\n")
    os.append("TaskIdx: " + taskIdx + "\n")
    os.append("VariationIdx: " + variationIdx + "\n")
    os.append("Task Description: " + taskDescription + "\n")
    os.append("\n")

    for (i <- 0 until this.length) {
      os.append(">>> " + historyActions(i) + "\n")
      os.append("Observation: " + historyObservations(i)._1 + "\n")
      //os.append("Free Look: " + historyFreeLook(i) + "\n")
      //os.append("Inventory: " + historyInventory(i) + "\n")
      os.append("Score: " + historyObservations(i)._2 + "\n")
      os.append("\n")
    }

    os.append("Action history: " + historyActions.mkString(", ") + "\n")
    os.append("Final Score: " + historyObservations.last._2 + "\n")
    os.append("isCompleted: " + historyObservations.last._3 + "\n")
    os.append("Notes:\n")
    for (note <- notes) {
      os.append(note + "\n")
    }
    os.append("\n------------------------------------------------------------------------\n\n")

    os.toString()
  }

}

object RunHistory {

  def sanitizeJSON(in:String):String = {
    var out = in.replace("\\", "\\\\")
    out = out.replace("\"", "\\\"")
    out = out.replace("\n", "\\n")
    out = out.replace("\r", "\\r")
    out = out.replace("\t", "\\t")

    return out
  }

}
