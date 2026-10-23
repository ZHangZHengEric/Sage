package scienceworld.tasks.goals

import scienceworld.objects.agent.Agent
import scienceworld.struct.EnvObject

import scala.collection.mutable
import scala.util.control.Breaks._

// Storage class for a single goal
class Goal(val description:String, val key:String, val keysMustBeCompletedBefore:Array[String]) {
  var satisfiedWithObject:Option[EnvObject] = None
  var defocusOnSuccess:Boolean = false
  var isOptional:Boolean = false

  def isGoalConditionSatisfied(obj:Option[EnvObject], isFirstGoal:Boolean, gs:GoalSequence, agent:Agent):GoalReturn = {
    return GoalReturn.mkSubgoalUnsuccessful()
  }

}


// Storage class for a sequence of goals
class GoalSequence(val subgoals:Array[Goal], optionalUnorderedSubgoals:Array[Goal] = Array.empty[Goal]) {

  var curSubgoalIdx:Int = 0
  var failed:Boolean = false
  var lastSatisfiedWithObject:Option[EnvObject] = None
  val subgoalsCompleted = Array.fill[Boolean](subgoals.length)(false)
  val storedValues = mutable.Map[String, String]()

  val optionalUnorderedSubgoalsCompleted = Array.fill[Boolean](optionalUnorderedSubgoals.length)(false)
  val completedKeys = mutable.Set[String]()

  this.reset()

  /*
   * Subgoals
   */
  def getCurrentSubgoal():Option[Goal] = {
    if (this.isCompleted()) return None
    return Some(this.subgoals(curSubgoalIdx))
  }

  def getSubgoalAtIdx(idx:Int):Option[Goal] = {
    if (this.isCompleted()) return None
    if ((idx < 0) || (idx > this.subgoals.length)) return None
    return Some( this.subgoals(idx) )
  }

  def getLastSubgoal():Option[Goal] = {
    if (this.curSubgoalIdx == 0) return None
    return Some( this.subgoals(this.curSubgoalIdx-1) )
  }

  def getLastSatisfiedObject():Option[EnvObject] = {
    return this.lastSatisfiedWithObject
  }

  def getNumCompletedSubgoals():Int = {
    var sum:Int = 0
    for (sgc <- subgoalsCompleted) {
      if (sgc == true) sum += 1
    }
    return sum
  }

  /*
   * Keys
   */
  def setKey(key:String, value:String): Unit = {
    storedValues(key) = value
  }

  def getKey(key:String):String = {
    if (!storedValues.contains(key)) return ""
    return storedValues(key)
  }

  // Keys that are specialized for subgoal completion
  def areSubgoalPrerequisitesCompleted(prereqKeys:Array[String]):Boolean = {
    // Case: True if there are no prerequisites
    if (prereqKeys.length == 0) return true

    // Check each prerequisite
    for (key <- prereqKeys) {
      if (!this.completedKeys.contains(key)) return false   // One prereq missing
    }
    return true
  }

  /*
   * Scoring
   */

  // Generate a normalized score (0-1) representing progress on this sequence of goals
  def score():Double = {
    val MAX_SCORE = 1.0f

    // If the task has failed, return a negative score
    if (this.isFailed()) return -1.0f

    // If the task has not failed, return normally calculated progress score

    val scoreOrdered = curSubgoalIdx.toDouble / subgoals.length.toDouble

    // Each unordered subgoal is worth a small amount --
    val scoreUnorderedUnit = (1/(subgoals.length.toDouble + 1)) / this.optionalUnorderedSubgoals.length.toDouble
    var scoreUnordered:Double = 0.0f
    for (i <- 0 until this.optionalUnorderedSubgoalsCompleted.length) {
      if (this.optionalUnorderedSubgoalsCompleted(i) == true) {
        scoreUnordered += scoreUnorderedUnit
      }
    }

    // Calculate total score
    var scoreTotal = scoreOrdered + scoreUnordered
    if (scoreTotal > MAX_SCORE) scoreTotal = MAX_SCORE

    println("Score: " + scoreTotal.formatted("%3.3f") + "    ordered: " + scoreOrdered.formatted("%3.3f") + "    unordered: " + scoreUnordered.formatted("%3.3f"))

    return scoreTotal
  }

  // Returns true if all the subgoals in this goal sequence are completed
  def isCompleted():Boolean = {
    if (curSubgoalIdx >= subgoals.length) return true
    // Otherwise
    return false
  }

  // Returns true if the goal has failed
  def isFailed():Boolean = {
    return this.failed
  }

  def setFailed() = {
    this.failed = true
  }

  def reset() {
    // Reset ordered subgoals
    this.curSubgoalIdx = 0
    this.lastSatisfiedWithObject = None

    // Reset unordered subgoals
    for (i <- 0 until this.optionalUnorderedSubgoalsCompleted.length) {
      this.optionalUnorderedSubgoalsCompleted(i) = false
    }

    // Reset failure
    this.failed = false
  }




  /*
   * Tick
   */

  def tick(objMonitor: ObjMonitor, agent:Agent): Unit = {
    this.tickOrderedSubgoals(objMonitor, agent)
    this.tickUnorderedSubgoals(objMonitor, agent)
  }


  /*
   * Evaluating subgoal success
   */

  // Checks the unordered subgoals for completion
  def tickUnorderedSubgoals(objMonitor: ObjMonitor, agent:Agent): Unit = {
    var numCompletedThisCycle = -1

    //println("* tickUnorderedSubgoals(): Started...")
    while (numCompletedThisCycle != 0) {
      numCompletedThisCycle = 0

      val numOptionalUnorderedSubgoals = optionalUnorderedSubgoals.length
      for (i <- 0 until numOptionalUnorderedSubgoals) {
        //println("\tEvaluating Subgoal " + i)
        // If this subgoal has not been completed
        if (optionalUnorderedSubgoalsCompleted(i) == false) {

          // Evaluate whether the subgoal has been completed
          val subgoal = optionalUnorderedSubgoals(i)
          breakable {
            // Do not process this subgoal if its prerequisites haven't been met
            if (!this.areSubgoalPrerequisitesCompleted(subgoal.keysMustBeCompletedBefore)) break()

            // First, check without any focus object
            val goalReturn = subgoal.isGoalConditionSatisfied(None, isFirstGoal = false, gs = this, agent)
            if (goalReturn.subgoalSuccess) {
              optionalUnorderedSubgoalsCompleted(i) = true
              if (subgoal.key.length > 0) this.completedKeys.add(subgoal.key)
              numCompletedThisCycle += 1
              //println("\t\tTrue")
              break
            }

            // Then, iterate through focus objects and check
            for (obj <- objMonitor.getMonitoredObjects()) {
              val goalReturn = subgoal.isGoalConditionSatisfied(Some(obj), isFirstGoal = false, gs = this, agent)
              if (goalReturn.subgoalSuccess) {
                optionalUnorderedSubgoalsCompleted(i) = true
                if (subgoal.key.length > 0) this.completedKeys.add(subgoal.key)
                numCompletedThisCycle += 1
                break
              }
            }
          }

        }
      }

    }

  }

  // Checks the current subgoal for completeness.  If completed, it increments the subgoals.
  def tickOrderedSubgoals(objMonitor: ObjMonitor, agent:Agent): Unit = {
    var firstSubgoalIdx = -1

    while (true) {
      var curSubgoal = this.getCurrentSubgoal()
      var subgoalIdx = this.curSubgoalIdx
      if (firstSubgoalIdx == -1) firstSubgoalIdx = subgoalIdx

      if (curSubgoal.isEmpty) return

      // Check each object in the set of monitored objects to see if it meets a subgoal condition
      var goalReturn:GoalReturn = GoalReturn.mkSubgoalUnsuccessful()
      breakable {

        while (true) {
          // Do not process this subgoal if it's prerequisites haven't been met
          if (this.areSubgoalPrerequisitesCompleted(curSubgoal.get.keysMustBeCompletedBefore)) {
            for (obj <- objMonitor.getMonitoredObjects()) {
              //println("Checking obj (" + obj.toStringMinimal() + ") against subgoal " + curSubgoalIdx)
              //println("## " + curSubgoal.get.getClass)

              val isFirstGoal = if (this.getNumCompletedSubgoals() == 0) true else false

              goalReturn = curSubgoal.get.isGoalConditionSatisfied(Some(obj), isFirstGoal, this, agent) // TODO: Also add a condition that checks for it with no focus?
              if (goalReturn.subgoalSuccess) {
                if (curSubgoal.get.satisfiedWithObject != None) this.lastSatisfiedWithObject = curSubgoal.get.satisfiedWithObject
                if (curSubgoal.get.defocusOnSuccess) objMonitor.clearMonitoredObjects() // Clear focus, if the goal asks to do this
                if (curSubgoal.get.key.length > 0) this.completedKeys.add(curSubgoal.get.key)
                break()
              }
              if (goalReturn.taskFailure) break()
            }
          } else {
            //println("Subgoal prerequisites not met")
          }

          //println("## No success or failure")

          // If we reach here, the subgoal hasn't been satisfied, and the task hasn't failed -- check if the subgoal is optional
          if (curSubgoal.get.isOptional) {
            //println("curSubgoal: " + curSubgoal)
            //println("curSubgoalIdx: " + curSubgoalIdx)
            curSubgoal = getSubgoalAtIdx(subgoalIdx + 1)
            if (curSubgoal.isEmpty) break()   // This condition should only happen if there are no more subgoals left (e.g. at end, or isComplete=True)
            subgoalIdx += 1
          } else {
            // If the subgoal isn't optional, then break
            break()
          }
        }
      }

      //print("##>> out of break")

      if (goalReturn.taskFailure) {
        //println ("Task failure.")
        this.setFailed()
      }

      if (goalReturn.subgoalSuccess) {
        // Current goal condition is satisfied -- test next goal condition until we find one that we don't satisfy, or complete the list.
        //println("Subgoal satisfied.")
        //curSubgoalIdx += 1
        this.curSubgoalIdx = subgoalIdx + 1
        if (curSubgoal.get.key.length > 0) this.completedKeys.add(curSubgoal.get.key)
      } else {
        // Current goal condition not satisfied -- return
        //println("Subgoal not satisfied.")
        return
      }

      // If we're not making progress solving progressive subgoals, break
      if (firstSubgoalIdx == this.curSubgoalIdx) return
    }

  }

  /*
   * String methods
   */
  def getProgressString():String = {
    val os = new StringBuilder()

    os.append("Completed keys: " + this.completedKeys.mkString(", ") + "\n")
    os.append("-" * 100 + "\n")
    os.append("Sequential Subgoals:\n")
    os.append("-" * 100 + "\n")
    for (i <- 0 until this.subgoals.length) {
      val subgoalDesc = this.subgoals(i).description
      val subgoalClass = this.subgoals(i).getClass.toString.split("\\.").last
      val passed = if (i<this.curSubgoalIdx) true else false

      os.append(i + "\t" + passed + "\t" + subgoalClass.formatted("%40s") + "\t" + subgoalDesc + "\n")
    }

    os.append("-" * 100 + "\n")
    os.append("Unordered and Optional Subgoals:\n")
    os.append("-" * 100 + "\n")
    for (i <- 0 until this.optionalUnorderedSubgoalsCompleted.length) {
      val subgoalDesc = this.optionalUnorderedSubgoals(i).description
      val subgoalClass = this.optionalUnorderedSubgoals(i).getClass.toString.split("\\.").last
      val passed = this.optionalUnorderedSubgoalsCompleted(i)

      os.append(i + "\t" + passed + "\t" + subgoalClass.formatted("%40s") + "\t" + subgoalDesc + "\n")
    }

    os.append("-" * 100 + "\n")


    // Return
    os.toString()
  }


}


// Storage class for return values
class GoalReturn(val subgoalSuccess:Boolean, val taskFailure:Boolean) {

}

object GoalReturn {

  def mkSubgoalSuccess():GoalReturn = {
    new GoalReturn(subgoalSuccess = true, taskFailure = false)
  }

  def mkTaskFailure():GoalReturn = {
    new GoalReturn(subgoalSuccess = false, taskFailure = true)
  }

  def mkSubgoalUnsuccessful():GoalReturn = {
    new GoalReturn(subgoalSuccess = false, taskFailure = false)
  }

}
