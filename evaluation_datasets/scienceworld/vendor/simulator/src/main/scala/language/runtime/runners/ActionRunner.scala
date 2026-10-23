package language.runtime.runners

import language.model.ActionRequestDef
import language.struct.{DynamicValue, EnvObject, ScopedVariableLUT, Taxonomy}

import scala.collection.mutable
import scala.collection.mutable.ArrayBuffer

class ActionRunner(val possibleActions:Array[ActionRequestDef], val taxonomy:Taxonomy) {
  var queuedActions = mutable.Map[String, Boolean]()
  val actionRequestsAtTime = new ArrayBuffer[mutable.Map[String, Boolean]]()        // (action_arg hashcode, true/false) -- all action requests will be true.
  val actionLUT = this.mkActionLUT(possibleActions)

  this.tick()


  /*
   * Tick
   */
  // Call this once at the start of each iteration.  Pushes past actions back one step, and lets new actions be written to the top of the stack (the latest timestep).
  def tick(): Unit = {
    actionRequestsAtTime.append( queuedActions )      // Add queued actions to request history
    queuedActions = mutable.Map[String, Boolean]()    // Reset queued actions
  }

  /*
   * Accessors
   */

  // Check whether a given action request is true/false (requested by key)
  def wasActionRequested(key:String):Boolean = {
    // Check if key exists -- if key doesn't exist, return default (false)
    if (!actionRequestsAtTime.last.contains(key)) return false
    // Otherwise
    return actionRequestsAtTime.last(key)
  }

  def wasActionRequested(actionName:String, arguments:ScopedVariableLUT):(Boolean, String, Boolean) = {   // (success, errorString, value)
    // If the action is unknown, return false
    if (!this.actionLUT.contains(actionName)) return (false, "ERROR: Unknown action (" + actionName + ").", false)

    val action = this.actionLUT(actionName)
    val (success, errorStr, key) = this.mkActionPredStr(action, arguments)
    if (!success) return (false, errorStr, false)

    return (true, "", this.wasActionRequested(key))
  }

  // Get all the actions that have been requested at this timestep
  def getActionsThisTimestep():Map[String, Boolean] = {
    actionRequestsAtTime.last.toMap
  }

  // Set the requested action (+args) to be true for this timestep
  def setActionRequest(action:ActionRequestDef, arguments:ScopedVariableLUT):(Boolean, String) = {      // (success, errorString)
    // Step 1: Type check parameters
    for (paramRef <- action.paramSigList.parameters) {
      val name = paramRef.name
      val requiredType = paramRef.objType
      // Check that this argument is populated
      if (!arguments.contains(name)) return (false, "ERROR: Call to action (" + action.name + ") is missing required parameter (" + name + ").")
      // Check that argument is an object
      val obj = arguments.get(name).get
      if (!obj.isObject()) return (false, "ERROR: Call to action (" + action.name + "): Parameter (" + name + ") has unexpected type (" + DynamicValue.TYPE_OBJECT + " expected, " + obj.getTypeStr() + " found).")
      // Check that the argument is the correct type
      val objType = obj.getObject().get.getType()

      //println ("name: " + name + " requiredType: " + requiredType + " objType: " + objType)

      if (objType != requiredType) {
        val (success, errStr, hypernyms) = taxonomy.getHypernyms(objType)
        //println(taxonomy.toString())
        //println ("hypernyms: " + hypernyms.mkString(", "))
        if (!hypernyms.contains(requiredType)) {
          return (false, "ERROR: Call to action (" + action.name + "): For parameter (" + name + "), expected type (" + requiredType + "), found type (" + objType + ").")
        }
      }


    }

    // Step 2: Set that action ran successfully in hashmap
    val (success, errorStr, key) = this.mkActionPredStr(action, arguments)
    if (!success) return (false, errorStr)
    // Success
    //actionRequestsAtTime.last(key) = true
    queuedActions(key) = true               // Add to queue
    // Return
    (true, "")
  }

  def setActionRequest(actionName:String, arguments:ScopedVariableLUT):(Boolean, String) = {      // (Success, errorString)
    // If the action is unknown, return false
    if (!this.actionLUT.contains(actionName)) return (false, "ERROR: Unknown action (" + actionName + ").")

    val action = this.actionLUT(actionName)
    return this.setActionRequest(action, arguments)
  }


  /*
   * Helpers
   */
  // Make a look-up table (LUT) for action-name-to-ActionRequestDef
  private def mkActionLUT(actions:Array[ActionRequestDef]):Map[String, ActionRequestDef] = {
    val out = mutable.Map[String, ActionRequestDef]()
    for (action <- actions) {
      out(action.name) = action
    }
    out.toMap
  }

  // Make a predicate(/action)-plus-arguments hashcode string from an action and given list of populating arguments
  def mkActionPredStr(action:ActionRequestDef, arguments:ScopedVariableLUT):(Boolean, String, String) = {   // (Success, errorString, output key)
    // Pack the assignments
    val argObjs = new ArrayBuffer[EnvObject]()
    // For each parameter
    for (i <- 0 until action.paramSigList.parameters.length) {
      // Get the object assigned to this parameter
      val param = action.paramSigList.parameters(i)
      val value = arguments.get(param.name)

      // Verify that the value exists and is a valid object
      if (value.isEmpty) return (false, "ERROR: Could not find assignment for Action (" + action.name + ") parameter (" + param.name + ").", "")
      if (!value.get.isObject()) return (false, "ERROR: Assignment for Action (" + action.name + ") parameter (" + param.name + ") is a different type than expected (expected: " + DynamicValue.TYPE_OBJECT + ", actual: " + value.get.getTypeStr() + ").", "")
      val obj = value.get.getObject().get

      // Pop it onto the arguments list (that will be passed to the string hashcode generator)
      argObjs.append(obj)
    }

    val strKey = PredicateRunner.mkPredStr(action.name, argObjs.toArray)
    return (true, "", strKey)
  }

  /*
   * String methods
   */

  override def toString():String = {
    val os = new StringBuilder
    os.append("ActionRunner: The following action requests are considered active in this timestep:\n")
    val trueKeys1 = this.actionRequestsAtTime.last.filter(_._2 == true).keySet.toArray.sorted

    if (trueKeys1.size > 0) {
      os.append("\t" + trueKeys1.mkString(", "))
    } else {
      os.append("\tNone")
    }
    os.append("\n")

    os.append("ActionRunner: The following action requests were queued in this timestep:\n")
    val trueKeys2 = this.queuedActions.filter(_._2 == true).keySet.toArray.sorted

    if (trueKeys2.size > 0) {
      os.append("\t" + trueKeys2.mkString(", "))
    } else {
      os.append("\tNone")
    }


    // Return
    os.toString()
  }
}
