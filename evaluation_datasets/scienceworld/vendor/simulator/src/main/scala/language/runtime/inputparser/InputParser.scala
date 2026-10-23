package language.runtime.inputparser

import language.model.{ActionExpr, ActionExprIdentifier, ActionExprOR, ActionRequestDef, ActionTrigger, ParamSigList}
import language.runtime.runners.{ActionRunner, PredicateRunner}
import language.struct.{DynamicValue, EnvObject, ScopedVariableLUT, Taxonomy, VariableLUT, WalkControl}

import scala.collection.mutable
import scala.collection.mutable.ArrayBuffer
import scala.util.control.Breaks._

/*
 * Parse plain text input commands (e.g. open the door, eat the apple) into a specific action request
 */

class InputParser(actionRequestDefs:List[ActionRequestDef], actionRunner:ActionRunner) {
  val stopWords = Array("a", "the")


  // Main entry point
  def parse(inputStr:String, objTreeRoot:EnvObject, agent:EnvObject): (Boolean, String, String) = {      // (Success, errorMessage, userString)
    // TODO: Only include observable objects in the list of all objects
    val tokens = this.tokenize(inputStr.toLowerCase)
    val allObjs = PredicateRunner.collectObjects(objTreeRoot).toArray

    //println ("inputStr: " + inputStr)

    val matchesOut = mutable.Map[String, Array[InputMatch]]()

    for (actionRequestDef <- actionRequestDefs) {
      //println ("ActionRequestDef: " + actionRequestDef.name)

      // Iterate through all possible triggers for this action
      val matches = new ArrayBuffer[InputMatch]
      for (trigger <- actionRequestDef.triggers) {
        matches.insertAll(matches.length, this.populate(tokens, actionRequestDef.paramSigList, trigger, allObjs) )
      }

      // Populate the actionRequestDef references in the storage class
      for (inputMatch <- matches) inputMatch.actionRequestDef = Some(actionRequestDef)

      // Populate the agent references in the storage class
      for (inputMatch <- matches) inputMatch.varLUT.set("agent", new DynamicValue(agent))

      // Store (but, only store for a given actionRequestDef if there are matches)
      if (matches.length > 0) {
        matchesOut(actionRequestDef.name) = matches.toArray
      }

      //println ("Pattern: " + actionRequestDef.name + "\t matches: " + matches.length)
    }


    // Check for (a) single match (good), (b) ambiguous matches, or (c) no matches
    val numMatches = this.countMatches(matchesOut)
    println ("numMatches: " + numMatches)

    // CASE 1: No matches
    if (numMatches == 0) {
      // No matches
      println ("No Matches")
      return (false, "", "No known action matches that input.")

    } else if (numMatches > 1) {
      // Ambiguous matches
      println ("Ambiguous matches")
      return (false, "", this.mkAmbiguousMessage(matchesOut) )

    } else {
      // Exactly one match
      println ("Exactly one match")
      // Step 1: Get one match
      var oneMatch:Option[InputMatch] = None
      for (key <- matchesOut.keySet) oneMatch = Some( matchesOut(key)(0) )

      // Step 2: Create action request
      val (success, errorStr) = actionRunner.setActionRequest(oneMatch.get.actionRequestDef.get, oneMatch.get.varLUT)
      if (!success) {
        // Error case
        val errStr = "ERROR: InputParser: Unable to post action request for action (" + oneMatch.get.actionRequestDef.get.name + ").\n" + errorStr
        println (errStr)
        return (false, errStr, "Error Encountered")
      }
      return (true, "", "Successfully parsed input into single action (" + oneMatch.get.actionRequestDef.get.name + ").")
    }
  }

  def countMatches(matches:mutable.Map[String, Array[InputMatch]]) : Int = {
    var numMatches:Int = 0
    for (key <- matches.keys) numMatches += matches(key).size
    return numMatches
  }

  def mkAmbiguousMessage(matches:mutable.Map[String, Array[InputMatch]]): String = {
    val os = new StringBuilder
    if (matches.keySet.size > 1) {
      // CASE: Multiple different actions are matched.
      os.append("Ambiguous request: Multiple different possible actions were matched to this input (")
      os.append( matches.keys.toArray.sorted.mkString(", ") + "). ")
      os.append("It's possible the action space needs to be refined to remove possible duplicate/ambiguous patterns.")
    } else {
      // CASE: One action, but multiple ways of filling it in
      val slots = new ArrayBuffer[Array[String]]
      // TODO...
      os.append("Ambiguous request: Multiple object matches.  I'm not sure which (X:TODO) you mean... \n")
    }

    // Return
    os.toString()
  }

  // Try to populate the slots of a given actionRequestDef with a given set of input tokens
  def populate(tokens:Array[String], paramSigList:ParamSigList, trigger:ActionTrigger, allObjs:Array[EnvObject]): Array[InputMatch] = {
    val paramLUT = paramSigList.paramLUT
    var sanitizedStr = tokens.mkString(" ")
    val out = new ArrayBuffer[InputMatch]

    val (success, matches) = this.populateHelper(sanitizedStr, trigger.pattern, allObjs, Array.empty[EnvObject])
    if (success) {
      // Remove duplicates
      val matchesNoDuplicates = this.removeDuplicates(matches)
      /*
      for (i <- 0 until matchesNoDuplicates.length) {
        println ("Match " + i + ": " + matchesNoDuplicates(i).mkString(",").toString)
      }
       */

      // Create an array of matches in an InputMatch storage class
      for (matchedObjs <- matchesNoDuplicates) {
        val varLUT = this.mkVariableLUT(trigger, matchedObjs)
        out.append( new InputMatch(trigger, varLUT) )
      }
    }

    return out.toArray
  }

  // Try to populate the slots of a given actionRequestDef with a given set of input tokens
  def populateHelper(inStr: String, pattern: List[ActionExpr], allObjs: Array[EnvObject], objMatchesSoFar: Array[EnvObject]): (Boolean, Array[Array[EnvObject]]) = {
    var sanitizedStr:String = inStr

    //println(" * populateHelper: sanitizedStr: " + sanitizedStr + "  pattern: " + pattern.mkString(", "))

    // Check if we're at the end of the trigger pattern
    if (pattern.length == 0) {
      if (inStr.trim.length == 0) {
        // Nothing left to parse in input string -- return match
        return (true, Array(objMatchesSoFar))
      } else {
        // Still input left to parse -- return false
        return (false, Array.empty[Array[EnvObject]])
      }
    }
    var objMatchesSoFar_ = new ArrayBuffer[EnvObject]
    objMatchesSoFar_.insertAll(0, objMatchesSoFar)
    val restOfPattern = pattern.slice(1, pattern.length)

    val out = new ArrayBuffer[Array[EnvObject]]()

    val elem = pattern(0)
    elem match {
      case ActionExprOR(orElements) => {
        val (success, matchStrings) = this.matchLexical(sanitizedStr, orElements)
        if (!success) return (false, Array.empty[Array[EnvObject]])
        for (matchString <- matchStrings) {
          val sanitizedStr = matchString
          val (successRecurse, objMatches) = this.populateHelper(sanitizedStr, restOfPattern, allObjs, objMatchesSoFar_.toArray)
          // If we reach here, success
          for (m <- objMatches) {
            out.append(m)
          }
        }
      }
      case ActionExprIdentifier(name) => {
        val (success, matchTuples) = this.matchObj(sanitizedStr, allObjs)
        if (!success) return (false, Array.empty[Array[EnvObject]])
        for (tupleMatch <- matchTuples) {
          val sanitizedStr = tupleMatch._1
          val objMatchPartial = objMatchesSoFar_.toArray ++ Array(tupleMatch._2)
          val (successRecurse, objMatches) = this.populateHelper(sanitizedStr, restOfPattern, allObjs, objMatchPartial)
          // If we reach here, success
          for (m <- objMatches) {
            out.append( m )
          }
        }

      }
    }

    if (out.length == 0) return (false, out.toArray)
    return (true, out.toArray)
  }


  // See if the start of a given string matches with a list of lexical possibilities.
  // e.g. inStr = "this is a test", possibilities=("a", "the", "this") would return (true, "is a test").
  def matchLexical(inStr:String, possibilities:List[String]):(Boolean, Array[String]) = {
    val out = new ArrayBuffer[String]()
    for (possibleStr <- possibilities) {
      if (inStr.startsWith(possibleStr)) {
        // Match -- consume possibility and return
        val outStr = inStr.substring( possibleStr.length ).trim()
        out.append(outStr)
      }
    }
    if (out.length == 0) return (false, Array.empty[String])
    // Return
    return (true, out.toArray)
  }

  // See if the start of a given string matches with a list of possible referents for objects
  def matchObj(inStr: String, allObjs: Array[EnvObject]): (Boolean, Array[(String, EnvObject)]) = {
    val out = new ArrayBuffer[(String, EnvObject)]

    for (obj <- allObjs) {
      val referents = InputParser.getObjectReferents(obj)
      for (referent <- referents) {
        if (inStr.startsWith(referent)) {
          val restOfStr = inStr.substring(referent.length).trim()
          out.append((restOfStr, obj))
        }
      }
    }
    // Return
    if (out.length == 0) return (false, out.toArray)
    return (true, out.toArray)
  }

  /*
   * Helper functions
   */
  def tokenize(inputStr:String):Array[String] = {
    val out = new ArrayBuffer[String]
    val tokens = inputStr.trim.replaceAll("\\s+", " ").split(" ")
    for (token <- tokens) {
      if (!stopWords.contains(token)) {
        out.append(token)
      }
    }
    // Return
    out.toArray
  }

  // Removes duplicate matches
  def removeDuplicates(in:Array[Array[EnvObject]]):Array[Array[EnvObject]] = {
    val out = new ArrayBuffer[ Array[EnvObject] ]()
    for (setIn <- in) {
      breakable {
        for (setOut <- out) {
          if (setIn.deep == setOut.deep) break      // Deep array comparison, to check for duplicates (if this ends up being too slow, refactor)
        }
        out.append(setIn)
      }
    }
    // Return
    out.toArray
  }

  // Populate a variable LUT based on the trigger variable identifiers and a parallel array of matched objects
  def mkVariableLUT(trigger:ActionTrigger, matchedObjs:Array[EnvObject]): ScopedVariableLUT = {
    // Step 1: Assemble a list of the variables in the trigger pattern
    val triggerElems = new ArrayBuffer[ActionExprIdentifier]
    for (patternElem <- trigger.pattern) {
      patternElem match {
        case x:ActionExprIdentifier => triggerElems.append(x)
        case _ => { // Do nothing
                  }
      }
    }

    // Step 2: Do assignments
    if (triggerElems.length != matchedObjs.length) throw new RuntimeException("ERROR: Number of trigger identifiers (" + triggerElems.mkString(", ") + ") is not the same as the number of matched objects (" + matchedObjs.length + ")")
    val outLUT = new ScopedVariableLUT()
    for (i <- 0 until triggerElems.length) {
      val triggerElem = triggerElems(i)
      val matchedObj = matchedObjs(i)
      outLUT.set(triggerElem.identifier, new DynamicValue(matchedObj))
    }

    // Return
    outLUT
  }




}


object InputParser {

  // DEBUG: Get a list of all possible valid referents, for debugging
  def getPossibleReferents(objTreeRoot:EnvObject):Array[String] = {
    val out = new ArrayBuffer[String]()

    val allObjs = PredicateRunner.collectObjects(objTreeRoot).toArray

    for (obj <- allObjs) {
      out.insertAll(out.size, getObjectReferents(obj) )
    }

    out.toArray
  }

  def getObjectReferents(obj:EnvObject):Array[String] = {
    val out = new ArrayBuffer[String]

    val possibleObjNames = obj.getProperty("referents")
    if (possibleObjNames.isDefined) {

      if (possibleObjNames.get.getTypeStr() == DynamicValue.TYPE_ARRAY) {
        // Array
        val refArray = possibleObjNames.get.getArray().get
        for (elem <- refArray) {
          val referent = elem.getString().get.toLowerCase
          out.append(referent)
        }
      } else {
        // Single value
        val referent = possibleObjNames.get.getString().get.toLowerCase
        out.append(referent)
      }
    }

    out.toArray
  }

}

// Storage class
class InputMatch(val actionTrigger:ActionTrigger, val varLUT:ScopedVariableLUT, var actionRequestDef:Option[ActionRequestDef] = None) {

  override def toString():String = {
    val os = new StringBuilder
    os.append("InputMatch(")
    os.append("ActionTrigger: " + actionTrigger + ", ")
    os.append("varLUT: " + varLUT.toString() )
    os.append(")")
    os.toString
  }
}
