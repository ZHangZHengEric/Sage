package language.model

import language.struct.Taxonomy

import scala.collection.mutable
import scala.collection.mutable.ArrayBuffer
import scala.util.control.Breaks._

class Program (val importList:Option[List[ImportFile]], val defines:Option[List[Define]], val classes:Option[List[ClassDef]], val predicates:Option[List[PredicateDef]], val actions:Option[List[ActionRequestDef]], val rules:Option[List[RuleDef]], val statements:Option[List[Statement]]) {
  // Store any errors that might have been found with this program after post-processing
  val errorsStr = new ArrayBuffer[String]
  val predicateLUT = this.mkPredicateLUT(predicates)
  val definesLUT = this.mkDefineLUT(defines)
  val actionLUT = this.mkActionLUT(actions)
  var classLUT = this.mkClassLUT(classes)
  var taxonomy:Taxonomy = Program.mkTaxonomyFromClasses(classes)

  // Constructor
  this.checkForErrors()

  // Blank constructor
  def this() {
    this(None, None, None, None, None, None, None)
  }

  /*
   * Taxonomy
   */
  /*
  def addTaxonomy(in:Taxonomy, taxonomyFilename:String):(Boolean, Array[String]) = {
    val (success, errorStrs) = this.taxonomy.combine(in)
    for (error <- errorStrs) this.addError("ERROR: Error when combining taxonomies (" + taxonomyFilename + "): " + error)
    return (success, errorStrs)
  }
   */

  /*
   * Error handling
   */
  def addError(str:String): Unit = {
    this.errorsStr.append(str)
  }

  def getErrors():Array[String] = errorsStr.toArray

  def hasErrors():Boolean = this.errorsStr.nonEmpty

  // Check for a few common errors
  def checkForErrors(): Unit = {
    // Check for duplicate predicates
    if (predicates.isDefined) {
      val duplicatePreds = predicates.get.groupBy(identity).collect { case (x, ys) if ys.lengthCompare(1) > 0 => x }
      for (duplicatePred <- duplicatePreds) {
        this.addError("Predicate (" + duplicatePred.name + ") is already defined.  This is likely a duplicate definition.")
      }
    }

    // Check for duplicate rules
    if (rules.isDefined) {
      val duplicateRules = rules.get.groupBy(identity).collect { case (x, ys) if ys.lengthCompare(1) > 0 => x }
      for (duplicateRule <- duplicateRules) {
        this.addError("Rule (" + duplicateRule.name + ") is already defined.  This is likely a duplicate definition.")
      }
    }

    // Check that rule predicate references are valid
    if (rules.isDefined) {
      for (rule <- rules.get) {
        val errors = this.checkForRuleErrors(rule)
        for (error <- errors) this.addError(error)
      }
    }
  }



  def checkForRuleErrors(rule:RuleDef):Array[String] = {
    val errorStrs = new ArrayBuffer[String]()

    val rulePreds = rule.preconditions ++ rule.postconditions                   // A list of all predicates in this rule

    for (predRef <- rulePreds) {
      breakable {
        val predName = predRef.name
        // Check that the predicate is valid/known
        if (!this.predicateLUT.contains(predName) && !this.actionLUT.contains(predName)) {
          var errStr = "ERROR: Unknown predicate (" + predName + ") referenced by rule (" + rule.name + ") on line " + rule.pos.line + " column " + predRef.pos.column + ":\n"
          errStr += rule.pos.longString + "\n"
          errorStrs.append(errStr)
          break
        }

        // Check that the predicate parameter references are valid/known
        var validParams = Set[String]()
        if (this.predicateLUT.contains(predName)) {
          val predDef = this.predicateLUT(predName)
          validParams = predDef.paramSigList.parameters.map(_.name).toSet     // Get a list of all valid predicate parameters
        } else if (this.actionLUT.contains(predName)) {
          val actionDef = this.actionLUT(predName)
          validParams = actionDef.paramSigList.parameters.map(_.name).toSet   // Get a list of all valid action parameters
        }

        val referencedParams = predRef.paramList.parameters.map(_.name).toSet // Get a list of all parameters passed as reference

        val missingParams = validParams.diff(referencedParams) // Parameters that are required, but missing in the reference
        val extraParams = referencedParams.diff(validParams) // Parameters that are provided in the rule/reference, but are not valid (i.e. not in the predicate definition)

        if ((missingParams.size > 0) || (extraParams.size > 0)) {
          var errStr = "ERROR: Error in predicate reference (" + predName + ") in rule (" + rule.name + ") on line " + rule.pos.line + ":\n"
          errStr += rule.pos.longString + "\n"

          if (missingParams.size > 0) errStr += "  Missing parameter(s): (" + missingParams.mkString(", ") + ") defined in the predicate definition, but missing when called in this rule.\n"
          if (extraParams.size > 0) errStr += "  Extra parameter(s): (" + extraParams.mkString(", ") + ") included in this rule, but are not valid parameters for this predicate (valid parameters: " + validParams.mkString(", ") + ").\n"

          errorStrs.append(errStr)
        }
      }
    }

    // Return
    errorStrs.toArray
  }


  /*
   * Classes
   */
  // Regenerate all the class definitions so that they include not only their defined properties, but also inherited properties.
  // Populates errors where duplicates are found without proper overrides.
  def inheritClassProperties(): Program = {
    val out = new ArrayBuffer[ClassDef]

    if (this.classes.isEmpty) {
      new Program(this.importList, this.defines, None, this.predicates, this.actions, this.rules, this.statements)
    }

    // Generate a set of new class definitions, with inherited class properties populated.
    val rootNames = taxonomy.getRootNames()
    val (newClassDefs, errors) = this.inheritClassPropertiesHelper(rootNames, List.empty[PropertyDefault], List.empty[PropertyFunction])

    // Return a new program
    val program = new Program(this.importList, this.defines, Some(newClassDefs), this.predicates, this.actions, this.rules, this.statements)

    // Because the error check for property inheritance is outside the normal error check, populate those errors
    for (error <- errors) {
      program.addError(error)
    }

    // Return
    program
  }

  private def inheritClassPropertiesHelper(classNames: Set[String], inheritedDefaultProperties:List[PropertyDefault], inheritedPropertyFunctions: List[PropertyFunction]): (List[ClassDef], Set[String]) = {
    val out = new ArrayBuffer[ClassDef]()
    val errors = mutable.Set[String]()

    for (className <- classNames) {
      var validDefaultProps = List.empty[PropertyDefault]
      var validPropFunctions = List.empty[PropertyFunction]

      // Get the bare class definition
      if (className != "Any") {     // Do not run on "Any" (the canonical base class)
        println("inheritClassPropertiesHelper(): " + className)
        val classDef = classLUT.get(className).get
        // Stage 1: Inheriting default properties
        val baseDefaultProps = classDef.propertyDefaults
        val baseDefaultPropNames = classDef.propertyDefaults.map(_.propName)

        // Check for duplicate default properties in the same class
        val duplicateDefaults = baseDefaultPropNames.groupBy(identity).collect { case (x, List(_,_,_*)) => x }
        if (duplicateDefaults.size > 0) {
          for (duplicate <- duplicateDefaults) {
            var lineNum = classDef.pos.line
            for (baseDefaultProp <- baseDefaultProps) {
              if (baseDefaultProp.propName == duplicate) lineNum = baseDefaultProp.pos.line
            }
            val errStr = "ERROR: Found two or more default properties (" + duplicate + ") in class (" + className + ") with the same name (around line " + lineNum + ")"
            errors.add(errStr)
          }
        }

        // Assemble a list of base and inherited default properties.
        // NOTE: Overriding a default property from a superclass is not required -- it just does it automatically (since this is just like an assignment in a constructor)
        val newDefaultProps = mutable.LinkedHashMap[String, PropertyDefault]()
        for (inheritedDefaultProp <- inheritedDefaultProperties) newDefaultProps(inheritedDefaultProp.propName) = inheritedDefaultProp
        for (baseDefaultProp <- baseDefaultProps) newDefaultProps(baseDefaultProp.propName) = baseDefaultProp


        // Stage 1: Inheriting property functions (with overrides, etc)
        val basePropFuncts = classDef.propertyFunctions
        val basePropFunctNames = basePropFuncts.map(_.propName)

        // Check to make sure there are no duplicate base default properties and property functions
        val allPropNames = baseDefaultPropNames ++ basePropFunctNames
        val duplicateAll = allPropNames.groupBy(identity).collect { case (x, List(_,_,_*)) => x }
        if (duplicateAll.size > 0) {
          for (duplicate <- duplicateAll) {
            val errStr = "ERROR: Duplicate property (" + duplicate + ") defined multiple times in class (" + className + ") around line " + classDef.pos.line + "."
            errors.add(errStr)
          }
        }

        // Check for duplicate inherited properties in the same class
        val duplicates = basePropFunctNames.groupBy(identity).collect { case (x, List(_,_,_*)) => x }
        if (duplicates.size > 0) {
          for (duplicate <- duplicates) {
            var lineNum = classDef.pos.line
            for (basePropFunct <- basePropFuncts) {
              if (basePropFunct.propName == duplicate) lineNum = basePropFunct.pos.line
            }
            val errStr = "ERROR: Found two or more property functions (" + duplicate + ") in class (" + className + ") with the same name (around line " + lineNum + ")"
            errors.add(errStr)
          }
        }

        // Add any inherited property functions to these property functions
        // First, take the ones specified by this class
        val newPropFuncts = mutable.LinkedHashMap[String, PropertyFunction]()
        for (basePropFunct <- basePropFuncts) newPropFuncts(basePropFunct.propName) = basePropFunct

        // Then, add the inherited ones
        for (inheritedPropFunct <- inheritedPropertyFunctions) {
          if (basePropFunctNames.contains(inheritedPropFunct.propName)) {
            // A duplicate property function name has been found -- check to see if it's a valid override
            var basePropFunct:Option[PropertyFunction] = None
            for (funct <- basePropFuncts) {
              if (funct.propName == inheritedPropFunct.propName) basePropFunct = Some(funct)
            }
            if (basePropFunct.get.isOverride) {
              // Override function
              newPropFuncts(inheritedPropFunct.propName) = basePropFunct.get      // This actually isn't required -- the base prop function is already in newPropFuncts
            } else {
              // Duplicate function without override -- throw error
              // Find line number of current function
              var lineNum1 = classDef.pos.line
              for (basePropFunct <- basePropFuncts) {
                if (basePropFunct.propName == inheritedPropFunct.propName) lineNum1 = basePropFunct.pos.line
              }
              // Find line number of superclass
              var lineNum2 = classDef.pos.line
              if (inheritedPropFunct.codeblock.length > 0) lineNum2 = inheritedPropFunct.codeblock(0).pos.line
              // Throw error
              val errStr = "ERROR: Found property function (" + inheritedPropFunct.propName + ") in class (" + className + ") around line " + lineNum1 + ", but a property with this name is already inherited from the superclass (" + classDef.superclass + ") around line " + lineNum2 + ".\nIf this function is an override, define as \"override propname " + inheritedPropFunct.propName + " = { ... }\""
              errors.add(errStr)
            }

          } else {
            // Simple case: this is a new/unknown function -- add it
            newPropFuncts(inheritedPropFunct.propName) = inheritedPropFunct
          }
        }

        // Check to make sure that there are no property functions with the same names as default properties -- if there are, remove the default property, keep the calculated (function) one.
        for (propName <- newPropFuncts.keys) {
          if (newDefaultProps.contains(propName)) {
            newDefaultProps.remove(propName)
          }
        }

        // Repack the storage class
        validDefaultProps = newDefaultProps.values.toList
        validPropFunctions = newPropFuncts.values.toList
        val newClassDef = new ClassDef(name = classDef.name, superclass = classDef.superclass, constructorDef = classDef.constructorDef, propertyDefaults = validDefaultProps, propertyFunctions = validPropFunctions)

        // Store
        out.append(newClassDef)
      }

      // Call recursively on any children classes
      val (success, errStr, directHyponyms) = taxonomy.getDirectHyponyms(className)
      if (!success) {
        this.addError(errStr)
      } else {
        val (children, errs) = this.inheritClassPropertiesHelper(directHyponyms, validDefaultProps, validPropFunctions)
        for (child <- children) {
          out.append(child)
          for (err <- errs) errors.add(err)
        }
      }
    }

    // Return
    (out.toList, scala.collection.immutable.TreeSet.empty[String] ++ errors)
  }

  /*
   * Helper functions
   */

  // Make a look-up table (LUT) of predicate-names-to-predicate-definitions
  def mkPredicateLUT(predicatesIn:Option[List[PredicateDef]]):Map[String, PredicateDef] = {
    val out = mutable.Map[String, PredicateDef]()
    // If empty, return blank hashmap
    if (predicatesIn.isEmpty) return out.toMap

    for (pred <- predicatesIn.get) {
      out(pred.name) = pred
    }

    // Return
    out.toMap
  }

  def mkClassLUT(classesIn:Option[List[ClassDef]]):Map[String, ClassDef] = {
    val out = mutable.Map[String, ClassDef]()
    if (classesIn.isEmpty) return out.toMap

    for (classDef <- classesIn.get) {
      out(classDef.name) = classDef
    }

    // Return
    out.toMap
  }

  def mkDefineLUT(definesIn:Option[List[Define]]):Map[String, String] = {
    val out = mutable.Map[String, String]()
    if (definesIn.isEmpty) return out.toMap

    for (define <- definesIn.get) {
      out(define.name) = define.replaceWith
    }

    // Return
    out.toMap
  }

  // Make a look-up table (LUT) for action-name-to-ActionRequestDef
  def mkActionLUT(actions:Option[List[ActionRequestDef]]):Map[String, ActionRequestDef] = {
    val out = mutable.Map[String, ActionRequestDef]()
    if (actions.isEmpty) return out.toMap

    for (action <- actions.get) {
      out(action.name) = action
    }
    out.toMap
  }

  /*
   * Operators
   */
  def +(that:Program):Program = {
    val importsCollected = new ArrayBuffer[ImportFile]
    if (this.importList.isDefined) importsCollected.insertAll(importsCollected.size, this.importList.get)
    if (that.importList.isDefined) importsCollected.insertAll(importsCollected.size, that.importList.get)

    val definesCollected = new ArrayBuffer[Define]
    if (this.defines.isDefined) definesCollected.insertAll(definesCollected.size, this.defines.get)
    if (that.defines.isDefined) definesCollected.insertAll(definesCollected.size, that.defines.get)

    val classesCollected = new ArrayBuffer[ClassDef]
    if (this.classes.isDefined) classesCollected.insertAll(classesCollected.size, this.classes.get)
    if (that.classes.isDefined) classesCollected.insertAll(classesCollected.size, that.classes.get)

    val predsCollected = new ArrayBuffer[PredicateDef]
    if (this.predicates.isDefined) predsCollected.insertAll(predsCollected.size, this.predicates.get)
    if (that.predicates.isDefined) predsCollected.insertAll(predsCollected.size, that.predicates.get)

    val actionsCollected = new ArrayBuffer[ActionRequestDef]
    if (this.actions.isDefined) actionsCollected.insertAll(actionsCollected.size, this.actions.get)
    if (that.actions.isDefined) actionsCollected.insertAll(actionsCollected.size, that.actions.get)

    val rulesCollected = new ArrayBuffer[RuleDef]
    if (this.rules.isDefined) rulesCollected.insertAll(rulesCollected.size, this.rules.get)
    if (that.rules.isDefined) rulesCollected.insertAll(rulesCollected.size, that.rules.get)

    val statementsCollected = new ArrayBuffer[Statement]
    if (this.statements.isDefined) statementsCollected.insertAll(statementsCollected.size, this.statements.get)
    if (that.statements.isDefined) statementsCollected.insertAll(statementsCollected.size, that.statements.get)

    val newProgram = new Program(Some(importsCollected.toList),
      Some(definesCollected.toList),
      Some(classesCollected.toList),
      Some(predsCollected.toList),
      Some(actionsCollected.toList),
      Some(rulesCollected.toList),
      Some(statementsCollected.toList) )

    // Return
    newProgram
  }


  /*
   * String methods
   */
  override def toString():String = {
    val os = new StringBuilder

    os.append("Defines:\n")
    if (defines.isDefined) {
      for (define <- defines.get) {
        os.append("\t" + define.toString() + "\n")
      }
    } else {
      os.append(("\tNone\n"))
    }

    os.append("Classes:\n")
    if (classes.isDefined) {
      for (classDef <- classes.get) {
        os.append("\t" + classDef.toString() + "\n")
      }
    } else {
      os.append("\tNone\n")
    }

    os.append("Predicates:\n")
    if (predicates.isDefined) {
      for (predicate <- predicates.get) {
        os.append("\t" + predicate.toString() + "\n")
      }
    } else {
      os.append("\tNone\n")
    }

    os.append("Actions:\n")
    if (actions.isDefined) {
      for (action <- actions.get) {
        os.append("\t" + action.toString() + "\n")
      }
    } else {
      os.append("\tNone\n")
    }


    os.append("Rules:\n")
    if (rules.isDefined) {
      for (rule <- rules.get) {
        os.append("\t" + rule.toString() + "\n")
      }
    } else {
      os.append("\tNone\n")
    }

    os.append("Statements:\n")
    if (statements.isDefined) {
      for (statement <- statements.get) {
        os.append("\t" + statement.toString() + "\n")
      }
    } else {
      os.append("\tNone\n")
    }


    // Return
    os.toString()
  }


}


object Program {

  def mkTaxonomyFromClasses(in:Option[List[ClassDef]]):Taxonomy = {
    val tax = new Taxonomy("")
    if (in.isEmpty) return tax

    for (classDef <- in.get) {
      val (success, errStr) = tax.addLink(classDef.name, classDef.superclass, autoAddParent = true)
      if (!success) {
        println ("ERROR: " + errStr)
        sys.exit(1)
      }
    }

    // Return
    tax
  }

}
