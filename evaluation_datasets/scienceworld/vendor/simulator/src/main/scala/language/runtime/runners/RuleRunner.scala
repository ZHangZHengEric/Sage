package language.runtime.runners

import language.model._
import language.struct._

import scala.collection.mutable
import scala.collection.mutable.ArrayBuffer
import scala.util.control.Breaks.{break, breakable}

class RuleRunner(val rules:Array[RuleDef], val predicateRunner:PredicateRunner, val debugOutput:Boolean = false) {
  val objsByType = predicateRunner.objsByType
  val predicateLUT = RuleRunner.mkPredicateLUT(predicateRunner.predicates)                // TODO: This should likely be passed in, and run only once -- running it every time RuleRunner() is generated is inefficient
  val actionRunner = predicateRunner.actionRunner
  val actionLUT = actionRunner.actionLUT
  val taxonomy = predicateRunner.taxonomy

  val ruleChangeLog = new ArrayBuffer[RuleChangeLog]

  //## Test
  if (debugOutput == true) println("RuleRunner(): Started...")
  for (rule <- rules) {
    if (debugOutput == true) println("Rule: " + rule.toString())
    val changeLog = evaluateRule(rule)
    this.ruleChangeLog.append(changeLog)
  }


  def evaluateRule(rule:RuleDef): RuleChangeLog = {
    // Note: A bunch of checking for valid rules (without missing/extra parameters to predicates, etc) is in the Program storage class -- so here rules are generally assumed to be valid (as much as can be determined without evaluating them), and minimal checking is done here in the evaluation.
    val numPreconditions = rule.preconditions.length
    val varTypesMap = mutable.Map[String, String]()
    val changeLog = new ArrayBuffer[ChangeLog]

    // Step 1: Create a hashmap that has the type of each variable

    // For each predicate in the preconditions
    for (precondIdx <- 0 until numPreconditions) {
      val precond = rule.preconditions(precondIdx)

      // Get the predicate
      val predicateName = precond.name

      if (!predicateLUT.contains(predicateName) && !actionLUT.contains(predicateName)) {
        val errStr = "ERROR: Predicate named (" + predicateName + ") referenced by rule (" + rule.name + ") cannot be found. (around line " + rule.pos.toString() + ")"
        println(errStr)
        sys.exit(1)
      }

      // Extract parameter signature list from either predicate or action
      var paramSigList = new ParamSigList(List.empty[ParamSig])
      if (predicateLUT.contains(predicateName)) {
        val predicate = predicateLUT(predicateName)
        paramSigList = predicate.paramSigList
      } else if (actionLUT.contains(predicateName)) {
        val action = actionLUT(predicateName)
        paramSigList = action.paramSigList
      }

      // For each parameter in the predicate
      for (predParam <- precond.paramList.parameters) {
        val predVarName = predParam.name
        val ruleVarName = predParam.value
        //##val varType = predicate.getVarType(predVarName)
        val varType = paramSigList.getVarType(predVarName)
        if (varTypesMap.contains(ruleVarName)) {
          // Check that they're the same type
          breakable {
            if (varTypesMap(ruleVarName) != varType) { // Check if direct match
              val (success, errStrHyponym, hypernyms) = taxonomy.getHypernyms(varType)
              if ((success) && (hypernyms.contains(varTypesMap(ruleVarName)))) {
                // The variable type in the rule is a valid hypernym of the type in the predicate -- OK
                break()
              }
              // If we reach here, there is a type mismatch between the variable type in a rule, and that variable's defined type in a predicate
              val errStr = "ERROR: Variable (" + ruleVarName + ") referenced by rule (" + rule.name + ") has different types (" + varTypesMap(ruleVarName) + ", " + varType + "). (around line " + rule.pos.toString() + ")"
              println(errStr)
              sys.exit(1)
            }
          }
        } else {
          // Add new type
          varTypesMap(ruleVarName) = varType
        }
      }
    }

    // Step 2: Create a set of parallel arrays that map assignments to specific predicates
    val flat = varTypesMap.toArray.sortBy(_._1)
    val varNames = flat.map(_._1)
    val varTypes = flat.map(_._2)
    // Also repack as a ParamSigList, so that we can use the iterator
    val elems = new ArrayBuffer[ParamSig]()
    for (i <- 0 until varNames.length) {
      val param = new ParamSig(varNames(i), varTypes(i))
      elems.append(param)
    }
    val paramSigList = new ParamSigList( elems.toList )
    // Also create a varName -> idx map
    val varNameToIdxLUT = mutable.Map[String, Int]()
    for (i <- 0 until varNames.length) {
      varNameToIdxLUT(varNames(i)) = i
    }

    // Step 3: Create the iterator
    val iter = new ParamIterator(paramSigList, objsByType)

    // Step 4: Run the iterator
    breakable {
      while (true) {
        // First, get a valid combination of objects that this predicate can be run with
        val combo = iter.next()
        if (combo.isEmpty) break()        // Break when no more valid combinations are available

        // Create string key for this run
        val strKeys = Array.fill[String](numPreconditions)("")
        for (precondIdx <- 0 until numPreconditions) {

            // First, Get the predicate
            val precond = rule.preconditions(precondIdx)
            val predicateName = precond.name
            if (this.predicateLUT.contains(predicateName)) {
              // For predicates
              val predicate = predicateLUT(predicateName)
              strKeys(precondIdx) = this.getKeyStr(precond, predicate, varNameToIdxLUT, combo.get)
            } else if (this.actionLUT.contains(predicateName)) {
              // For actions
              val action = actionLUT(predicateName)
              strKeys(precondIdx) = this.getKeyStr(precond, action, varNameToIdxLUT, combo.get)
            }
        }

        // Then, lookup the values for these predicate runs
        //## println ("Iter " + iter.count)
        var runPostcondition:Boolean = true
        for (strKey <- strKeys) {
          val result = predicateRunner.getResult(strKey)
          //## println("\t" + strKey + "\t" + result)
          if (result == false) runPostcondition = false
        }

        // If the preconditions are all true, then run the postcondition's setters.
        if (runPostcondition) {
          val postConditions = rule.postconditions
          //println("\tTODO: All preconditions are true -- should run postcondition")
          val changes = this.runPostcondition(rule, rule.postconditions, varNameToIdxLUT, combo.get)
          changeLog.insertAll(changeLog.length, changes)                                        // Store changelog
        }
      }
    }

    return new RuleChangeLog(rule, changeLog.toArray)
  }


  def runPostcondition(rule:RuleDef, postconditions:List[PredicateRef], varNameToIdxLUT:mutable.Map[String, Int], assignments:Array[EnvObject]): Array[ChangeLog] = {
    val changeLog = new ArrayBuffer[ChangeLog]

    for (postCondIdx <- 0 until postconditions.length) {
      val postcond = postconditions(postCondIdx)
      if (debugOutput) println ("runPostcondition(): " + postcond.toString())

      val predicateName = postcond.name
      // Determine postcondition type: predicate or action
      if (this.predicateLUT.contains(predicateName)) {
        val predicate = predicateLUT(predicateName) // TODO: Also allow running actions

        // Pack variable assignments
        val varLUT = new ScopedVariableLUT()
        val errors = new ArrayBuffer[String]()
        for (predParam <- postcond.paramList.parameters) {
          val predVarName = predParam.name
          val ruleVarName = predParam.value
          val varType = predicate.getVarType(predVarName)
          val objArg = assignments(varNameToIdxLUT(ruleVarName))
          varLUT.set(predVarName, new DynamicValue(objArg))
          // TODO: Also check for missing assignments -- variables in predicates that were not assigned?

          // Type checking -- check that assignment is of the correct type.
          val (successHyp, errStrHyp, hypernyms) = taxonomy.getHypernyms(objArg.getType())
          if (!successHyp) {
            println ("ERROR: Unknown class type (" + objArg.getType() + ") when running predicate (" + predicate.name + ") in rule (" + rule.name + ") around line " + rule.pos.line + ".")
            println (errStrHyp)
            sys.exit(1)
          }
          if (!hypernyms.contains(varType)) {
            errors.append("ERROR: In rule (" + rule.name + "), predicate (" + predicate.name + ") argument (" + ruleVarName + "): Expected type (" + varType + "), found type (" + objArg.getType() + "). \nThis error can happen when the preconditions have more generic types than the postconditions.")
          }
        }

        if (errors.length > 0) {
          println( errors.mkString("\n") )
          sys.exit(1)
        }

        // Run predicate
        if (debugOutput) {
          println("Predicate: " + postcond.paramList.toString())
          println("* runPostCondition(): VarLUT: ")
          println(varLUT.toString())
        }

        // Run predicate (and create change)
        val changes = predicateRunner.runSetter(predicate, varLUT)

        // Record change
        changeLog.insertAll(changeLog.length, changes) // Store any changes made by this run

      } else if (this.actionLUT.contains(predicateName)) {
        val actionName = predicateName
        val action = actionLUT(actionName)

        // Pack variable assignments
        val varLUT = new ScopedVariableLUT()
        for (predParam <- postcond.paramList.parameters) {
          val predVarName = predParam.name
          val ruleVarName = predParam.value
          val varType = action.getVarType(predVarName)
          val objArg = assignments(varNameToIdxLUT(ruleVarName))
          varLUT.set(predVarName, new DynamicValue(objArg))
          // TODO: Also check for missing assignments -- variables in predicates that were not assigned?
        }

        // Run predicate
        if (debugOutput) {
          println("Action: " + postcond.paramList.toString())
          println("* runPostCondition(): VarLUT: ")
          println(varLUT.toString())
        }

        // Queue action
        val (success, errStr) = actionRunner.setActionRequest(actionName, varLUT)
        if (!success) {
          println ("ERROR: Unable to queue action request (" + actionName + ") in rule (" + rule.name + ") postcondition:\n" + errStr)
          sys.exit(1)
        }

        // Record change?
        // TODO: Add action request (and their source) to changelog?

      }

    }

    return changeLog.toArray
  }


  /*
   * Helper functions
   */

  // Get the key for looking up the results of a run predicate
  def getKeyStr(predRef:PredicateRef, predicate:PredicateDef, varNameToIdxLUT:mutable.Map[String, Int], assignments:Array[EnvObject]): String = {
    val name = predicate.name
    val paramList = predRef.paramList
    val paramSigList = predicate.paramSigList
    this.getKeyStr(name, paramList, paramSigList, varNameToIdxLUT, assignments)
  }

  def getKeyStr(predRef:PredicateRef, action:ActionRequestDef, varNameToIdxLUT:mutable.Map[String, Int], assignments:Array[EnvObject]): String = {
    val name = action.name
    val paramList = predRef.paramList
    val paramSigList = action.paramSigList
    this.getKeyStr(name, paramList, paramSigList, varNameToIdxLUT, assignments)
  }

  def getKeyStr(name:String, paramList:ParamList, paramSigList:ParamSigList, varNameToIdxLUT:mutable.Map[String, Int], assignments:Array[EnvObject]): String = {
    // First, get the assignments
    val assignmentLUT = mutable.Map[String, EnvObject]()
    //for (predParam <- predRef.paramList.parameters) {
    for (predParam <- paramList.parameters) {
      val predVarName = predParam.name
      val ruleVarName = predParam.value
      val varIdx = varNameToIdxLUT(ruleVarName)
      val objAssignment = assignments(varIdx)
      assignmentLUT(predVarName) = objAssignment
    }

    // Then, put the assignments in the same order as the predicate signature
    val numParam = paramSigList.parameters.length
    val argsOut = new Array[EnvObject](numParam)
    for (i <- 0 until numParam) {
      val param = paramSigList.parameters(i)
      argsOut(i) = assignmentLUT(param.name)
    }

    // Then, call the string hashkey function
    return PredicateRunner.mkPredStr(name, argsOut)
  }

  /*
   * String methods
   */
  def toStringChangeLog():String = {
    val os = new mutable.StringBuilder()

    for (ruleIdx <- 0 until ruleChangeLog.length) {
      os.append(ruleIdx + ": " + ruleChangeLog(ruleIdx).toString())
    }
    os.toString()
  }


  def toHTMLChangeLog():String = {
    val os = new StringBuilder

    for (ruleIdx <- 0 until ruleChangeLog.length) {
      os.append( ruleChangeLog(ruleIdx).toHTML(ruleIdx.toString) )
    }

    // Return
    os.toString()
  }


}

object RuleRunner {

  // Make a lookup table that goes from the predicate name to the actual predicate structure
  def mkPredicateLUT(predicates:Array[PredicateDef]):Map[String, PredicateDef] = {
    val out = mutable.Map[String, PredicateDef]()

    for (predicate <- predicates) {
      out(predicate.name) = predicate
    }

    // Return
    out.toMap
  }

}
