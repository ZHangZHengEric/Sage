package language.runtime

import language.model.{AddObjToWorld, ArrayAppend, ArrayDef, ArrayElem, ArrayRemove, Assignment, AssignmentArrayElem, AssignmentObjProp, Bool, BuiltInFunction, ClassDef, ConditionElem, ConditionExpr, ConditionLR, ConditionOperator, ConditionalOperator, DeleteObject, Exit, Expr, ForLoop, ForLoopArrayElem, ForRange, ForRangeParsed, Identifier, IfStatement, IfStatementCondition, MoveObject, NegatedExpr, Number, ObjectCreate, ObjectProperty, Operator, ParamList, Print, PrintLog, RequestAction, Return, SetAgent, Statement, Str}
import language.runtime.runners.{ActionRunner, ObjectPropertyRunner, PredicateRunner}
import language.struct.{ChangeLog, ChangeLogObjMove, ChangeLogObjProp, DynamicValue, EnvObject, ScopedVariableLUT, VariableLUT, WalkControl}

import scala.collection.mutable
import scala.collection.mutable.ArrayBuffer
import scala.util.control.Breaks._

class Interpreter(val definesLUT:Map[String, String] = Map[String, String](), classLUT:Map[String, ClassDef], actionRunner:ActionRunner) {
  var objectTreeRoot = new EnvObject()
  var scopedVariableLUT = new ScopedVariableLUT()
  val changeLog = new ArrayBuffer[ChangeLog]()
  private var mainAgent:Option[EnvObject] = None
  var runPropertyFunctions:Boolean = false
  val taxonomy = actionRunner.taxonomy
  val consoleOutputBuffer = new ArrayBuffer[String]()

  objectTreeRoot.setType(Interpreter.DEFAULT_ROOT_OBJECT_NAME)

  def setObjectTreeRoot(root:EnvObject) = this.objectTreeRoot = root
  def setVariableLUT(varLUT:ScopedVariableLUT) = this.scopedVariableLUT = varLUT

  def getMainAgent():Option[EnvObject] = this.mainAgent
  def setRunPropertyFunctions(value:Boolean): Unit = {
    this.runPropertyFunctions = value
  }

  /*
   * Console output
   */
  def consoleOutputPrintln(outStr:String) {
    this.consoleOutputBuffer.append(outStr)
  }

  def consoleOutputClear() {
    this.consoleOutputBuffer.clear()
  }

  def getConsoleOutput():Array[String] = {
    this.consoleOutputBuffer.toArray
  }

  def mergeConsoleOutput(interpreter:Interpreter) = {
    this.consoleOutputBuffer.insertAll(this.consoleOutputBuffer.size, interpreter.getConsoleOutput() )
  }

  /*
   * Object instantiation
   */
  private def mkObjectInstance(objectName:String, classType:String, paramList:ParamList):(Boolean, String, EnvObject) = {
    // Step 1: Get class definition
    if (!this.classLUT.contains(classType)) return (false, "ERROR: Cannot create new object -- unknown class type (" + classType + "). ", new EnvObject())
    val classDef = this.classLUT(classType)

    // Step 2: Create new object instance, add base properties
    val newObjInst = new EnvObject()
    newObjInst.setType(classType)
    newObjInst.setName(objectName)

    // Step 3: Add default properties
    for (defaultProp <- classDef.propertyDefaults) {
      val propName = defaultProp.propName
      val (value, success, errStr) = this.calculateExpression(defaultProp.valueExpr)
      if (!success) {
        return (false, "ERROR: Error calculating default property expression (" + propName + ") in class (" + classType + ") during object initialization.", new EnvObject())
      }
      newObjInst.setProperty(propName, value )
    }

    // Step 4: Run constructor code
    // Step 4A: First, pack the variable assignments into a VariableLUT
    val (successVar, errStrVar, variableAssignments) = PredicateRunner.packAssignments(paramList, this.scopedVariableLUT)
    if (!successVar) return (false, "ERROR: Can't instantiate object of class type (" + classType + ").\n" + errStrVar, new EnvObject)

    // Step 4B: Then, check that all required constructor parameters are specified
    val (successCheck, errStrCheck) = PredicateRunner.checkParamList(classDef.constructorDef.paramSigList, variableAssignments, taxonomy, callNameForErrMsg = "class (" + classDef.name + ")")
    if (!successCheck) return (false, "ERROR: Can't instantiate object of class type (" + classType + ").\n" + errStrCheck, new EnvObject)

    // Step 4C: Then, run the constructor
    val codeblock = classDef.constructorDef.statements
    if (codeblock.isDefined) {
      variableAssignments.set("this", new DynamicValue(newObjInst)) // Create variable LUT with reference to "this" object
      val newFauxInterpreter = new Interpreter(definesLUT, classLUT, actionRunner)
      newFauxInterpreter.setVariableLUT(variableAssignments)
      newFauxInterpreter.setObjectTreeRoot(this.objectTreeRoot)
      val result = newFauxInterpreter.walkOneStep(codeblock.get)
      if (result.failed())  return (false, "ERROR: Error encountered when running constructor for class (" + classDef.name + ").", new EnvObject)
      this.mergeConsoleOutput(newFauxInterpreter)
    }

    // Return
    return (true, "", newObjInst)
  }

  /*
   * Calculating Expressions
   */

  // Number, Str, Identifier, ObjectProperty, Operator, ObjectCreate
  private def calculateExpression(e:Expr, variableLUT:ScopedVariableLUT = this.scopedVariableLUT):(DynamicValue, Boolean, String) = {
    val extendedErrorStr = e.toStringCode()

    e match {
      case Number(value) => return (new DynamicValue(value), true, "")
      case Str(value) => return (new DynamicValue(value), true, "")
      case Bool(value) => return (new DynamicValue(value), true, "")
      case NegatedExpr(expr) => {
        val (result, success, errorStr) = calculateExpression(expr, variableLUT)
        if (!success) return (new DynamicValue(), success, errorStr)
        if (!result.isBoolean()) return (new DynamicValue(), false, "Negated Expression is not boolean (" + expr.toStringCode() + ").")
        val value = !result.getBoolean().get
        return (new DynamicValue(value), true, "")
      }
      case Identifier(name) => {
        // Look up value of variable
        if (!variableLUT.contains(name)) return (new DynamicValue(), false, "Unknown identifier (" + name + ").")
        return (variableLUT.get(name).get, true, "")
      }
      case ObjectProperty(instname, propname) => {
        // Look up object
        if (!variableLUT.contains(instname)) return (new DynamicValue(), false, "Unknown object instance (" + instname + ").")
        val objInstDV = variableLUT.get(instname).get
        if (!objInstDV.isObject()) return (new DynamicValue(), false, "Identifier with that name (" + instname + ") is not of type object (found type: " + objInstDV.getTypeStr() + ")")

        // Get property name (with the added step that the property name might be a reference to a DEFINE, and need to be substituted by that define)
        var propNameProcessed = propname
        if (this.definesLUT.contains(propname)) propNameProcessed = this.definesLUT(propname)     // Do substitution

        // Look up property value
        val objInst = objInstDV.getObject().get
        val objType = objInst.getType()
        val classDef = this.classLUT(objType)
        if ((runPropertyFunctions == true) && (classDef.propertyFunctionLUT.contains(propNameProcessed))) {
          // CASE: The object properties should be calculated at runtime -- calculate the property
          val propFunction = classDef.propertyFunctionLUT(propNameProcessed)
          val newFauxInterpreter = new Interpreter(definesLUT, classLUT, actionRunner)
          newFauxInterpreter.setRunPropertyFunctions(true)
          ObjectPropertyRunner.runPropertyFunction(objInst, propFunction, newFauxInterpreter, this.objectTreeRoot, this.classLUT)
          this.mergeConsoleOutput(newFauxInterpreter)       // Append any console output from the faux interpreter
        }
        // Read the property value
        val propValue = objInst.getProperty(propNameProcessed)
        if (propValue.isEmpty) {
          if (this.definesLUT.contains(propname)) return (new DynamicValue(), false, "Property with name (" + propNameProcessed + ", substituted with define " + propname + ") has no value for that object instance (" + instname + ").  Valid property names: " + objInst.getPropertyNames().mkString(", "))
          return (new DynamicValue(), false, "Property with name (" + propNameProcessed + ") has no value for that object instance (" + instname + ").  Valid property names: " + objInst.getPropertyNames().mkString(", "))
        }
        // If we reach here, the property name is valid
        return (propValue.get, true, "")
      }
      case ObjectCreate(objtype, objname, paramlist) => {
        //## TODO: Run parameter lists
        val (success, errStr, newObjInst) = this.mkObjectInstance(objname, objtype, paramlist)
        if (!success) return (new DynamicValue(), false, "ERROR: Error during object creation (" + objtype + ").\n" + errStr)
        // Pack into a DynamicValue
        return (new DynamicValue(newObjInst), true, "")
      }
      case Operator(op, left, right) => {
        val (leftResult, leftSuccess, leftErrorStr) = calculateExpression(left, variableLUT)
        if (!leftSuccess) return (new DynamicValue(), leftSuccess, leftErrorStr)
        val (rightResult, rightSuccess, rightErrorStr) = calculateExpression(right, variableLUT)
        if (!rightSuccess) return (new DynamicValue(), rightSuccess, rightErrorStr)

        op match {
          case "*" => {
            val (result, success, errorStr) = leftResult.multiply(rightResult)
            return (result, success, errorStr + " (" + extendedErrorStr + ")")
          }
          case "/" => {
            val (result, success, errorStr) = leftResult.divide(rightResult)
            return (result, success, errorStr + " (" + extendedErrorStr + ")")
          }
          case "%" => {
            val (result, success, errorStr) = leftResult.modulo(rightResult)
            return (result, success, errorStr + " (" + extendedErrorStr + ")")
          }
          case "+" => {
            val (result, success, errorStr) = leftResult.add(rightResult)
            return (result, success, errorStr + " (" + extendedErrorStr + ")")
          }
          case "-" => {
            val (result, success, errorStr) = leftResult.subtract(rightResult)
            return (result, success, errorStr + " (" + extendedErrorStr + ")")
          }
          case _ => {
            return (new DynamicValue(), false, "ERROR: Unknown operator (" + op + ") (" + extendedErrorStr + ")")
          }

        }
      }
      case BuiltInFunction(functionName, args) => {
        return this.evaluateBuiltInFunction(functionName, args)
      }
      case ArrayDef(elemExprs) => {
        return this.createArray(elemExprs)
      }
      case ArrayElem(name, elemIdxExpr) => {
        return this.getArrayElem(name, elemIdxExpr)
      }
      case _ => {
        return (new DynamicValue(), false, "ERROR: Unknown expression primitive or function (" + e.toString + ").")
      }
    }

    return (new DynamicValue(), false, "Unknown expression term.")
  }

  // Create an array
  def createArray(elemExprs:List[Expr]): (DynamicValue, Boolean, String) = {
    val out = new ArrayBuffer[DynamicValue]
    // Evaluate expressions for each array element
    for (elemIdx <- 0 until elemExprs.length) {
      val elemExpr = elemExprs(elemIdx)
      val (value, success, errorStr) = this.calculateExpression(elemExpr)
      if (!success) return (new DynamicValue(), false, "ERROR: Unable to calculate expression when initializing array for element (" + elemIdx + ").\n" + elemExpr.toStringCode() + "\n" + errorStr)
      out.append(value)
    }

    // Create array
    return (new DynamicValue(out.toArray), true, "")
  }

  def getArrayElem(arrayName:String, elemIdxExpr:Expr): (DynamicValue, Boolean, String) = {
    // Step 2: Calculate element index expression
    val (elemIdxValue, success, errorStr) = this.calculateExpression(elemIdxExpr)
    if (!success) return (new DynamicValue(), false, "ERROR: Error when calculating expression for array element index:\n" + elemIdxExpr.toStringCode())

    // Step X: Get array
    val arrayRef = scopedVariableLUT.get(arrayName)
    if (arrayRef.isEmpty) return (new DynamicValue(), false, "ERROR: Unknown variable name (" + arrayName + ").")

    // Step 3: Get element
    val (successElem, errorStrElem, elemValue) = arrayRef.get.getElem( elemIdxValue )
    if (!successElem) return (new DynamicValue(), false, "ERROR: Unable to access element of array.\n" + errorStrElem)

    return (elemValue, true, "")
  }

  // Evaluate built-in functions
  def evaluateBuiltInFunction(functionName:String, args:List[Expr]):(DynamicValue, Boolean, String) = {
    val genericErrStr = "ERROR: Error encountered when evaluating '" + functionName +"'. \n"
    functionName match {

      // Math
      case "round" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedArgs = 1)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val (roundSuccess, roundErrStr, arg) = evaledArgs(0).round()
        if (!roundSuccess) return (new DynamicValue(), false, genericErrStr + roundErrStr + "\n")
        return (arg, true, "")
      }
      case "ceil" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedArgs = 1)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val (roundSuccess, roundErrStr, arg) = evaledArgs(0).ceil()
        if (!roundSuccess) return (new DynamicValue(), false, genericErrStr + roundErrStr + "\n")
        return (arg, true, "")
      }
      case "floor" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedArgs = 1)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val (roundSuccess, roundErrStr, arg) = evaledArgs(0).floor()
        if (!roundSuccess) return (new DynamicValue(), false, genericErrStr + roundErrStr + "\n")
        return (arg, true, "")
      }
      case "abs" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedArgs = 1)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val (roundSuccess, roundErrStr, arg) = evaledArgs(0).abs()
        if (!roundSuccess) return (new DynamicValue(), false, genericErrStr + roundErrStr + "\n")
        return (arg, true, "")
      }
      case "exp" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedArgs = 1)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val (roundSuccess, roundErrStr, arg) = DynamicValue.exp( evaledArgs(0) )
        if (!roundSuccess) return (new DynamicValue(), false, genericErrStr + roundErrStr + "\n")
        return (arg, true, "")
      }
      case "sqrt" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedArgs = 1)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val (roundSuccess, roundErrStr, arg) = DynamicValue.sqrt( evaledArgs(0) )
        if (!roundSuccess) return (new DynamicValue(), false, genericErrStr + roundErrStr + "\n")
        return (arg, true, "")
      }
      case "log10" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedArgs = 1)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val (roundSuccess, roundErrStr, arg) = DynamicValue.log10( evaledArgs(0) )
        if (!roundSuccess) return (new DynamicValue(), false, genericErrStr + roundErrStr + "\n")
        return (arg, true, "")
      }
      // Trigonometry
      case "sin" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedArgs = 1)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val (roundSuccess, roundErrStr, arg) = DynamicValue.sin( evaledArgs(0) )
        if (!roundSuccess) return (new DynamicValue(), false, genericErrStr + roundErrStr + "\n")
        return (arg, true, "")
      }
      case "cos" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedArgs = 1)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val (roundSuccess, roundErrStr, arg) = DynamicValue.cos( evaledArgs(0) )
        if (!roundSuccess) return (new DynamicValue(), false, genericErrStr + roundErrStr + "\n")
        return (arg, true, "")
      }
      case "tan" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedArgs = 1)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val (roundSuccess, roundErrStr, arg) = DynamicValue.tan( evaledArgs(0) )
        if (!roundSuccess) return (new DynamicValue(), false, genericErrStr + roundErrStr + "\n")
        return (arg, true, "")
      }
      case "asin" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedArgs = 1)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val (roundSuccess, roundErrStr, arg) = DynamicValue.asin( evaledArgs(0) )
        if (!roundSuccess) return (new DynamicValue(), false, genericErrStr + roundErrStr + "\n")
        return (arg, true, "")
      }
      case "acos" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedArgs = 1)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val (roundSuccess, roundErrStr, arg) = DynamicValue.acos( evaledArgs(0) )
        if (!roundSuccess) return (new DynamicValue(), false, genericErrStr + roundErrStr + "\n")
        return (arg, true, "")
      }
      case "atan" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedArgs = 1)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val (roundSuccess, roundErrStr, arg) = DynamicValue.atan( evaledArgs(0) )
        if (!roundSuccess) return (new DynamicValue(), false, genericErrStr + roundErrStr + "\n")
        return (arg, true, "")
      }

      // Array
      case "len" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedArgs = 1)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val array = evaledArgs(0)
        val (sizeSuccess, sizeErrStr, arg) = array.size()
        if (!sizeSuccess) return (new DynamicValue(), false, genericErrStr + sizeErrStr + "\n")
        return (arg, true, "")
      }
      case "empty" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedArgs = 1)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, emptyErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + emptyErrorStr)
        // Do Function
        val array = evaledArgs(0)
        val (emptySuccess, emptyErrStr, arg) = array.isEmpty()
        if (!emptySuccess) return (new DynamicValue(), false, genericErrStr + emptyErrStr + "\n")
        return (arg, true, "")
      }
      case "contains" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedMinArgs = 2, expectedMaxArgs = 2)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, emptyErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + emptyErrorStr)
        // Do Function
        val (containsSuccess, containsErrStr, arg) = DynamicValue.contains( evaledArgs(0), evaledArgs(1) )
        if (!containsSuccess) return (new DynamicValue(), false, genericErrStr + containsErrStr + "\n")
        return (arg, true, "")
      }

      // Objects
      case "hasProperty" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedMinArgs = 2, expectedMaxArgs = 2)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, emptyErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + emptyErrorStr)
        // Do Function
        val (containsSuccess, containsErrStr, arg) = DynamicValue.hasProperty( evaledArgs(0), evaledArgs(1) )
        if (!containsSuccess) return (new DynamicValue(), false, genericErrStr + containsErrStr + "\n")
        return (arg, true, "")
      }

      // Math (multi-argument)
      case "min" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedMinArgs = 1, expectedMaxArgs = 10)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val (roundSuccess, roundErrStr, arg) = DynamicValue.min(evaledArgs)
        if (!roundSuccess) return (new DynamicValue(), false, genericErrStr + roundErrStr + "\n")
        return (arg, true, "")
      }
      case "max" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedMinArgs = 1, expectedMaxArgs = 10)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val (roundSuccess, roundErrStr, arg) = DynamicValue.max(evaledArgs)
        if (!roundSuccess) return (new DynamicValue(), false, genericErrStr + roundErrStr + "\n")
        return (arg, true, "")
      }
      case "pow" => {
        // Checks
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedMinArgs = 2, expectedMaxArgs = 2)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val (roundSuccess, roundErrStr, arg) = DynamicValue.pow(evaledArgs(0), evaledArgs(1))
        if (!roundSuccess) return (new DynamicValue(), false, genericErrStr + roundErrStr + "\n")
        return (arg, true, "")
      }

      // Type Casting
      case "str" => {
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedArgs = 1)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val (roundSuccess, roundErrStr, arg) = evaledArgs(0).str()
        if (!roundSuccess) return (new DynamicValue(), false, genericErrStr + roundErrStr + "\n")
        return (arg, true, "")
      }

      case "type" => {
        val (parseSuccess, parseErrorStr) = this.mkArgErrorStr(functionName, args, expectedArgs = 1)
        if (!parseSuccess) return (new DynamicValue(), false, genericErrStr + parseErrorStr)
        val (evalSuccess, evalErrorStr, evaledArgs) = this.evaluateArgs(args)
        if (!evalSuccess) return (new DynamicValue(), false, genericErrStr + evalErrorStr)
        // Do Function
        val typeStr = new DynamicValue( evaledArgs(0).getTypeStr() )
        return (typeStr, true, "")
      }

      case _ => {
        return (new DynamicValue(), false, genericErrStr + "ERROR: Unknown function (" + functionName + ").\n")
      }
    }

  }

  // Evaluate the expressions in all the arguments in a list of arguments.  Check for any errors.
  private def evaluateArgs(args:List[Expr]):(Boolean, String, Array[DynamicValue]) = {
    val out = new Array[DynamicValue](args.length)

    for (i <- 0 until args.length) {
      val (value, success, errStr) = this.calculateExpression(args(i))
      if (!success) {
        val argErr = args(i).toStringCode()
        return (false, "ERROR: Error evaluating argument (" + argErr + ").\n" + errStr, Array.empty[DynamicValue])
      }
      out(i) = value
    }

    // Return
    return (true, "", out)
  }

  private def mkArgErrorStr(functionName:String, args:List[Expr], expectedArgs:Int):(Boolean, String) = {
    this.mkArgErrorStr(functionName, args, expectedMinArgs = expectedArgs, expectedMaxArgs = expectedArgs)
  }

  private def mkArgErrorStr(functionName:String, args:List[Expr], expectedMinArgs:Int, expectedMaxArgs:Int):(Boolean, String) = {
    // Success case
    if ((args.length >= expectedMinArgs) && (args.length <= expectedMaxArgs)) return (true, "")
    // Failure cases
    if (args.length < expectedMinArgs) return (false, "ERROR: Missing argument(s) to '" + functionName + "'.  Expected minimum of " + expectedMinArgs + " arguments, found " + args.length + ".")
    if (args.length > expectedMaxArgs) return (false, "ERROR: Too many argument(s) to '" + functionName + "'.  Expected maximum of " + expectedMaxArgs + " arguments, found " + args.length + ".")

    // Default
    return (false, "ERROR: Unknown error parsing arguments to function '" + functionName + "'.")
  }

  /*
   * Calculating conditional expressions
   */
  def conditionalLogic(conditionExpr:ConditionExpr, trueBranch:List[Statement]):(Boolean, WalkControl, String) = {    // (isConditionTrue, WalkControl)
    val (success, conditionResult, errorString) = this.calculateConditionalExpr(conditionExpr)

    // Debug
    //println("ConditionalLogic: Result: " + conditionResult + "  Success: " + success + "   ErrorString: " + errorString)
    // Check for failure
    if (!success) {
      val errStr = "ERROR: Returned with failure on evaluating expression: " + conditionExpr.toString() + "\n" + errorString
      return (false, WalkControl.mkFailure(), errStr)
    }

    // If condition is true, then start walking the branch logic
    if (conditionResult == true) {
      // Push on a new scope to the variable LUT for inside the conditional
      scopedVariableLUT.push()

      // Start walking the branch logic
      val walkResult = this.walkOneStep(trueBranch)
      if (walkResult.success) {
        // TODO: Pop variable scope
      }

      // Pop off the new (conditional) scope from the variable LUT
      scopedVariableLUT.pop()

      return (true, walkResult, "")
    } else {
      return (false, WalkControl.mkSuccess(), "")
    }

  }

  def calculateConditionalExpr(e:ConditionExpr): (Boolean, Boolean, String) = {    // (Success, evaluation result, errorString)
    e match {
      case ConditionElem(cond) => {
        cond match {
          case c:ConditionLR => {
            val (success, result, errorString) = this.evaluateConditionLR(c)
            if (!success) return (false, false, "ERROR: Failed to evaluate expression: " + c.toString() + "\n" + errorString)
            return (success, result, errorString)
          }
        }
      }
      case ConditionOperator(op, left, right) => {
        val (successLeft, resultLeft, errorStringLeft) = this.calculateConditionalExpr(left)
        if (!successLeft) return (false, false, "ERROR: Failed to evaluate left side of expression: " + left.toString() + "\n" + errorStringLeft)
        val (successRight, resultRight, errorStringRight) = this.calculateConditionalExpr(right)
        if (!successRight) return (false, false, "ERROR: Failed to evaluate right side of expression: " + right.toString() + "\n" + errorStringLeft)

        op match {
          case ConditionalOperator.BOOL_AND => {
            val condEval = resultLeft && resultRight
            return (true, condEval, "")
          }
          case ConditionalOperator.BOOL_OR => {
            val condEval = resultLeft || resultRight
            return (true, condEval, "")
          }
          case _ => {
            return (false, false, "ERROR: Unknown boolean operator (" + op + ") in expression: " + e.toString())
          }
        }
      }
    }

  }

  def evaluateConditionLR(condLR:ConditionLR):(Boolean, Boolean, String) = {    // (Success, evaluation result, errorString)
    // Calculate left and right sides of expression
    val (valueLeft, successLeft, errorStrLeft) = calculateExpression(condLR.left)
    if (!successLeft) return (false, false, errorStrLeft)
    val (valueRight, successRight, errorStrRight) = calculateExpression(condLR.right)
    if (!successRight) return (false, false, errorStrRight)

    // Make sure that we're comparing the same types
    if (valueLeft.getTypeStr() != valueRight.getTypeStr()) {
      var errorStr = "ERROR: Comparing expressions of different types (" + condLR.left.toStringCode() + " [" + valueLeft.getTypeStr() + "] vs " + condLR.right.toStringCode() + " [" + valueRight.getTypeStr() + "]). "
      return (false, false, errorStr)
    }

    // Do evaluation
    val (success, result, errorStr) = valueLeft.booleanOperator(condLR.op, valueRight)
    // Return
    return (success, result, errorStr)
  }

  /*
   * Loops
   */
  // Parse a for loop range (of the form for (x <- 0 until 10) ).
  // Input is a ForRange, which contains a list of Expressions (Expr) for each of startIdx, until, and by.
  // Output is a ForRangeParsed, which contains the actual values (ints) for startIdx, until, and by.
  def evaluateForRange(range:ForRange):(Boolean, String, ForRangeParsed) = {      // (Success, errorString, result)
    val errMessageGenericSuffix = " in for loop range around line " + range.pos.line + ":\n" + range.pos.longString + "\n"

    // Start Index
    val startIdxExpr = range.startIdx
    val (valueStart, successStart, errStrStart) = this.calculateExpression(startIdxExpr)
    if (!successStart) {
      val errStr = "ERROR: Error calculating 'start' index " + errMessageGenericSuffix + errStrStart
      return (false, errStr, new ForRangeParsed())
    }
    if (!valueStart.isNumber()) return (false, "ERROR: Type error when calculating 'start' index (expected: " + DynamicValue.TYPE_NUMBER + ", found: " + valueStart.getTypeStr() + ") " + errMessageGenericSuffix, new ForRangeParsed())
    if (!valueStart.isInt()) return (false, "ERROR: Value error when calculating 'start' index (value (" + valueStart.getNumber().get.toString + "), expected integer) " + errMessageGenericSuffix, new ForRangeParsed())

    // Until Index
    val untilIdxExpr = range.until
    val (valueUntil, successUntil, errStrUntil) = this.calculateExpression(untilIdxExpr)
    if (!successUntil) {
      val errStr = "ERROR: Error calculating 'until' index " + errMessageGenericSuffix + errStrUntil
      return (false, errStr, new ForRangeParsed())
    }
    if (!valueUntil.isNumber()) return (false, "ERROR: Type error when calculating 'until' index (expected: " + DynamicValue.TYPE_NUMBER + ", found: " + valueUntil.getTypeStr() + ") " + errMessageGenericSuffix, new ForRangeParsed())
    if (!valueUntil.isInt()) return (false, "ERROR: Value error when calculating 'until' index (value (" + valueUntil.getNumber().get.toString + "), expected integer) " + errMessageGenericSuffix, new ForRangeParsed())

    // By (optional)
    val byExpr = range.by
    var valueBy:Int = 1
    if (byExpr.isDefined) {
      var (valueBy_, successBy, errStrBy) = this.calculateExpression(byExpr.get)
      if (!successBy) {
        if (!successUntil) {
          val errStr = "ERROR: Error calculating 'by' " + errMessageGenericSuffix + errStrBy
          return (false, errStr, new ForRangeParsed())
        }
      }
      if (!valueBy_.isNumber()) return (false, "ERROR: Type error when calculating 'by' (expected: " + DynamicValue.TYPE_NUMBER + ", found: " + valueBy_.getTypeStr() + ") " + errMessageGenericSuffix, new ForRangeParsed())
      if (!valueBy_.isInt()) return (false, "ERROR: Value error when calculating 'by' index (value (" + valueBy_.getNumber().get.toString + "), expected integer) " + errMessageGenericSuffix, new ForRangeParsed())
      valueBy = valueBy_.getInt().get
    }

    // If we reach here, the expressions were evaluated successfully
    val forRangeParsed = new ForRangeParsed(valueStart.getInt().get, valueUntil.getInt().get, valueBy)

    // Return
    (true, "", forRangeParsed)
  }


  /*
   * Statement Logic
   */

  def printStatement(strOut:String): Boolean = {
    println(">>> " + strOut)
    this.consoleOutputPrintln(strOut)

    return true
  }

  def printLogStatement(strOut:String): Boolean = {
    println(">>> " + strOut)

    return true
  }


  def mkErrorString(statement:Statement):String = {
    val os = new mutable.StringBuilder()

    os.append("ERROR encountered on line " + statement.pos.line + ": \n" + statement.pos.longString)

    // Return
    os.toString
  }

  /*
   * Running statements
   */
  def walkOneStep(tree:List[Statement]): WalkControl = {

    // Check if we have statements to process
    if (!tree.isEmpty) {

      //println("Statement: " + tree.head)
      //println("Position: " + tree.head.pos.toString())

      // Examine the first statement
      tree.head match {
        // List all statements and their processing bits here
        /*
         * Return
         */
        case Return(expr) => {
          val (exprValue, success, errorStr) = this.calculateExpression(expr, scopedVariableLUT)
          if (!success) {
            // Error case
            println ("ERROR: Unable to calculate assignment. ")
            println (errorStr + "\n" + this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }

          // Then, make sure the expression is a boolean
          // NOTE: Commented out, because now a return value can be anything packed into a DynamicValue
          /*
          if (!exprValue.isBoolean()) {
            println ("ERROR: Expected expression value of type " + DynamicValue.TYPE_BOOLEAN + ", instead found type (" + exprValue.getTypeStr() + ")")
            println (this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }
           */


          // If we reach here, the return value is boolean (valid)
          return WalkControl.mkReturn( exprValue )
        }

        case Exit(exitCode) => {
          // Hard exit
          println ("Reached exit (line " + tree.head.pos.line + ").")
          sys.exit(exitCode)
        }

        /*
         * Setting main agent
         */
        case SetAgent(expr) => {
          // First, evaluate expression
          val (exprValue, success, errorStr) = this.calculateExpression(expr, scopedVariableLUT)
          if (!success) {
            // Error case
            println ("ERROR: Unable to calculate assignment. ")
            println (errorStr + "\n" + this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }

          // Next, make sure that the expression is an object
          if (!exprValue.isObject()) {
            println ("ERROR: SetAgent failed as expression is of an unexpected type (expected: " + DynamicValue.TYPE_OBJECT + ", found " + exprValue.getTypeStr() + ")")
            println (this.mkErrorString(tree.head))
            return WalkControl.mkFailure()
          }

          // Set the agent
          this.mainAgent = Some(exprValue.getObject().get)

          // Continue walking
          return this.walkOneStep(tree.tail)
        }

        /*
         * Assignment
         */
        case Assignment(varName, expr, firstdefinition) => {
          // First, evaluate expression
          val (exprValue, success, errorStr) = this.calculateExpression(expr, scopedVariableLUT)
          if (!success) {
            // Error case
            println ("ERROR: Unable to calculate assignment. ")
            println (errorStr + "\n" + this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }

          // If firstdefinition is flagged, check that the variable hasn't already been defined
          if (firstdefinition == true) {
            if (scopedVariableLUT.contains(varName)) {
              println ("ERROR: Variable (" + varName + ") is already defined. ")
              println ("ScopedVariableLUT:\n" + scopedVariableLUT.toString())
              println (this.mkErrorString(tree.head))
              return WalkControl.mkFailure()
            }
          } else {
            // If firstdefinition is false, check that the variable exists
            if (!scopedVariableLUT.contains(varName)) {
              println ("ERROR: Variable (" + varName + ") has not yet been defined. ")
              println ("ScopedVariableLUT:\n" + scopedVariableLUT.toString())
              println (this.mkErrorString(tree.head))
              return WalkControl.mkFailure()
            }
          }

          // Success, set variable value
          scopedVariableLUT.set(varName, exprValue)
          return this.walkOneStep(tree.tail)
        }

        case AssignmentObjProp(objProp, expr) => {
          val (exprValue, success, errorStr) = this.calculateExpression(expr, scopedVariableLUT)
          if (!success) {
            // Error case
            println ("ERROR: Unable to calculate assignment. ")
            println (errorStr + "\n" + this.mkErrorString(tree.head) )

            return WalkControl.mkFailure()
          }

          // Get object
          val value = scopedVariableLUT.get(objProp.name)
          if (!value.isDefined) {
            // Error case
            println ("ERROR: Unknown variable name (" + objProp.name + "). ")
            println (errorStr + "\n" + this.mkErrorString(tree.head) )

            return WalkControl.mkFailure()
          }

          val obj = value.get.getObject()
          if (!obj.isDefined) {
            // Error case
            println ("ERROR: Variable name (" + objProp.name + ") is not of type " + DynamicValue.TYPE_OBJECT + " (" + value.get.getTypeStr() + "). ")
            println (errorStr + "\n" + this.mkErrorString(tree.head) )

            return WalkControl.mkFailure()
          }

          // Handle property name substitution from DEFINES
          // Get property name (with the added step that the property name might be a reference to a DEFINE, and need to be substituted by that define)
          var propNameProcessed = objProp.property
          if (this.definesLUT.contains(objProp.property)) propNameProcessed = this.definesLUT(objProp.property)     // Do substitution

          // Check to see if we're setting a property that is automatically populated (i.e. defined in the class definition)
          val classDef = classLUT.get(obj.get.getType())
          if (classDef.isDefined) {
            if (classDef.get.propertyFunctionLUT.contains(propNameProcessed)) {
              val propFunct = classDef.get.propertyFunctionLUT(propNameProcessed)
              val warningStr = "WARNING: An assignment was made to object property (" + propNameProcessed + ") around line " + tree.head.pos.line + ", but this property is overwritten each tick from the classes (" + obj.get.getType() + ") property function (around line " + propFunct.pos.line + ")"
              println(warningStr)
              // TODO: Add to a list of warnings?
            }
          }

          // Set property

          // Get old property (for logging)
          val oldPropertyValue = obj.get.getProperty(propNameProcessed).getOrElse(new String("None"))
          // Change property to new value
          obj.get.setProperty(propNameProcessed, exprValue)
          // Store log of change (for logging)
          this.changeLog.append( new ChangeLogObjProp(obj.get, propNameProcessed, oldPropertyValue.toString, exprValue.toString()) )

          // Save object (TODO: is this necessary?)
          scopedVariableLUT.set(objProp.name, new DynamicValue(obj.get) )

          return this.walkOneStep(tree.tail)
        }

        case AssignmentArrayElem(arrayElem, expr) => {
          // Calculate value expression
          val (exprValue, success, errorStr) = this.calculateExpression(expr, scopedVariableLUT)
          if (!success) {
            // Error case
            println ("ERROR: Unable to calculate assignment. ")
            println (errorStr + "\n" + this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }

          // Get array
          val arrayVariable = scopedVariableLUT.get(arrayElem.name)
          if (!arrayVariable.isDefined) {
            // Error case
            println ("ERROR: Unknown variable name (" + arrayElem.name + "). ")
            println (errorStr + "\n" + this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }

          // Get array element index
          val (elemIdxValue, successElem, errorStrElem) = this.calculateExpression(arrayElem.elemIdxExpr)
          if (!successElem) {
            println("ERROR: Error when calculating expression for array element index:\n" + arrayElem.elemIdxExpr.toStringCode())
            println(errorStrElem + "\n" + this.mkErrorString(tree.head))
            return WalkControl.mkFailure()
          }

          // Set element value
          val (successSet, errorStrSet) = arrayVariable.get.setElem(elemIdxValue, exprValue)
          if (!successSet) {
            println ("ERROR: Error when setting array element value:\n" + arrayElem.elemIdxExpr.toStringCode())
            println (errorStrSet + "\n" + this.mkErrorString(tree.head))
            return WalkControl.mkFailure()
          }

          return this.walkOneStep(tree.tail)
        }

        /*
         * Array built-in functions
         */
        case ArrayAppend(varExpr, valueExpr) => {
          // Calculate value expression
          val (exprValue, successValue, errorStrValue) = this.calculateExpression(valueExpr, scopedVariableLUT)
          if (!successValue) {
            println ("ERROR: Unable to calculate expression. \n" + errorStrValue + "\n" + this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }

          // Calculate value expression
          val (exprVar, successVar, errorStrVar) = this.calculateExpression(varExpr, scopedVariableLUT)
          if (!successVar) {
            println ("ERROR: Unable to calculate expression. \n" + errorStrVar + "\n" + this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }

          val (successOp, errorStrOp) = exprVar.appendElem( exprValue )
          if (!successOp) {
            println ("ERROR: Unable to append to array. \n" + errorStrOp + "\n" + this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }

          return this.walkOneStep(tree.tail)
        }

        case ArrayRemove(varExpr, valueExpr) => {
          // Calculate value expression
          val (exprValue, successValue, errorStrValue) = this.calculateExpression(valueExpr, scopedVariableLUT)
          if (!successValue) {
            println ("ERROR: Unable to calculate expression. \n" + errorStrValue + "\n" + this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }

          // Calculate value expression
          val (exprVar, successVar, errorStrVar) = this.calculateExpression(varExpr, scopedVariableLUT)
          if (!successVar) {
            println ("ERROR: Unable to calculate expression. \n" + errorStrVar + "\n" + this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }

          val (successOp, errorStrOp) = exprVar.removeElem( exprValue )
          if (!successOp) {
            println ("ERROR: Unable to remove element from array. \n" + errorStrOp + "\n" + this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }

          return this.walkOneStep(tree.tail)        }

        /*
         * Add Object to World
         */
        case AddObjToWorld(expr) => {
          // First, calculate value of expression
          val (exprValue, success, errorStr) = this.calculateExpression(expr, scopedVariableLUT)
          if (!success) {
            // Error case
            println ("ERROR: Unable to calculate assignment. ")
            println (errorStr + "\n" + this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }
          // Then, make sure the expression is an object
          if (!exprValue.isObject()) {
            println ("ERROR: Expected expression value of type " + DynamicValue.TYPE_OBJECT + ", instead found type (" + exprValue.getTypeStr() + ")")
            println (this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }
          // Then, add the object to the object tree
          // TODO: Currently, just add to the root (but ultimately should be added to specific objects)
          this.objectTreeRoot.addObject( exprValue.getObject().get )

          return walkOneStep(tree.tail)
        }

        case DeleteObject(expr) => {
          // First, calculate value of expression
          val (exprValue, success, errorStr) = this.calculateExpression(expr, scopedVariableLUT)
          if (!success) {
            // Error case
            println ("ERROR: Unable to calculate assignment. ")
            println (errorStr + "\n" + this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }
          // Then, make sure the expression is an object
          if (!exprValue.isObject()) {
            println ("ERROR: Expected expression value of type " + DynamicValue.TYPE_OBJECT + ", instead found type (" + exprValue.getTypeStr() + ")")
            println (this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }
          // To delete the object, just remove it from it's container (which should remove it from the object tree)
          val obj = exprValue.getObject().get
          obj.removeAndResetContainer()

          return walkOneStep(tree.tail)
        }

        case MoveObject(toMoveExpr, moveToExpr) => {
          // First, calculate value of expressions
          // Step 1A: Calculate value of object 'toMove'
          val (exprValueToMove, success1, errorStr1) = this.calculateExpression(toMoveExpr, scopedVariableLUT)
          if (!success1) {
            // Error case
            println ("ERROR: Unable to calculate assignment. ")
            println (errorStr1 + "\n" + this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }
          // Then, make sure the expression is an object
          if (!exprValueToMove.isObject()) {
            println ("ERROR: Expected expression value of type " + DynamicValue.TYPE_OBJECT + ", instead found type (" + exprValueToMove.getTypeStr() + ")")
            println (toMoveExpr.toStringCode())
            println (this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }

          // Step 1B: Calculate value of object to move the first object to
          val (exprValueMoveTo, success2, errorStr2) = this.calculateExpression(moveToExpr, scopedVariableLUT)
          if (!success2) {
            // Error case
            println ("ERROR: Unable to calculate assignment. ")
            println (errorStr2 + "\n" + this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }
          // Then, make sure the expression is an object
          if (!exprValueMoveTo.isObject()) {
            println ("ERROR: Expected expression value of type " + DynamicValue.TYPE_OBJECT + ", instead found type (" + exprValueMoveTo.getTypeStr() + ")")
            println (moveToExpr.toStringCode())
            println (this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }

          // Perform the move
          val objToMove = exprValueToMove.getObject().get
          val oldContainer = objToMove.getContainer()
          val objContainer = exprValueMoveTo.getObject().get
          objContainer.addObject( objToMove )

          // Logging
          changeLog.append( new ChangeLogObjMove(objToMove, oldContainer, Some(objContainer)) )

          return walkOneStep(tree.tail)
        }

        /*
         * Running (/Posting) Actions
         */
        case RequestAction(predicateRef) => {
          val actionName = predicateRef.name
          val actionParams = predicateRef.paramList

          // Step 1: Populate arguments for call
          val args = new ScopedVariableLUT()
          for (param <- actionParams.parameters) {
            val paramName = param.name
            val paramValue = param.value
            val objValue = this.scopedVariableLUT.get(paramValue)
            if (objValue.isEmpty) {
              // Error case
              println ("ERROR: Action (" + predicateRef.name + "): Unknown object name (" + paramValue + ")")
              println (this.mkErrorString(tree.head) )
              return WalkControl.mkFailure()
            }

            if (!objValue.get.isObject()) {
              // Error case
              println ("ERROR: Action (" + predicateRef.name + ") parameter (" + paramName + "): Expected type " + DynamicValue.TYPE_OBJECT + ", found type " + objValue.get.getTypeStr() + ".")
              println (this.mkErrorString(tree.head) )
              return WalkControl.mkFailure()
            }

            // Set argument
            args.set(paramName, objValue.get)
          }

          // Step 2: Run call (make action request)
          val (success, errorStr) = this.actionRunner.setActionRequest(actionName, args)
          if (!success) {
            // Error case
            println ("ERROR: Unable to post action request for action (" + predicateRef.name + ").")
            println (errorStr + "\n" + this.mkErrorString(tree.head) )
            return WalkControl.mkFailure()
          }

          // Step 3: Walk
          return walkOneStep(tree.tail)
        }

        /*
         * Printing
         */
        case Print(expr) => {
          // Step 1: Calculate expression value
          val (exprValue, success, errorStr) = this.calculateExpression(expr, scopedVariableLUT)
          if (!success) {
            // Error case
            println ("ERROR: Unable to calculate assignment. ")
            println (errorStr + "\n" + this.mkErrorString(tree.head) )

            return WalkControl.mkFailure()
          }

          // Step 2: Print string
          val successPrint = printStatement(exprValue.toString())
          if (successPrint) {
            // Continue walking
            return walkOneStep(tree.tail)
          } else {
            return WalkControl.mkFailure()
          }
        }

        case PrintLog(expr) => {
          // Step 1: Calculate expression value
          val (exprValue, success, errorStr) = this.calculateExpression(expr, scopedVariableLUT)
          if (!success) {
            // Error case
            println ("ERROR: Unable to calculate assignment. ")
            println (errorStr + "\n" + this.mkErrorString(tree.head) )

            return WalkControl.mkFailure()
          }

          // Step 2: Print string
          val successPrint = printLogStatement(exprValue.toString())
          if (successPrint) {
            // Continue walking
            return walkOneStep(tree.tail)
          } else {
            return WalkControl.mkFailure()
          }
        }

        /*
         * Loops
         */
        case ForLoop(varName, rangeRaw, codeblock) => {
          // First, interpret the range
          val (success, errStr, range) = this.evaluateForRange(rangeRaw)
          if (!success) {
            println ("ERROR: Unable to evaluate for loop range expression.")
            println (errStr + "\n" + this.mkErrorString(tree.head))
            return WalkControl.mkFailure()
          }
          println ("FORLOOP: Range: " + range.toString())


          // Then, run the code
          for (iterValue <- range.startIdx until range.until by range.by) {
            // Push on a new scope to the variable LUT for inside the loop
            scopedVariableLUT.push()

            // Assign iterator the value in the variable LUT
            // TODO: Add scoping
            scopedVariableLUT.set(varName, new DynamicValue(iterValue))

            // Run the code in this loop
            val result = this.walkOneStep(codeblock)

            // Pop off new scope from variable LUT
            scopedVariableLUT.pop()

            // Check for errors, returns, etc
            if (result.failed() || result.hasReturnValue()) {
              // Return
              return result
            }
          }

          return walkOneStep(tree.tail)
        }

        case ForLoopArrayElem(varName, arrayExpr, codeblock) => {
          // First, find the array
          val (array_, success, errStr) = this.calculateExpression(arrayExpr)
          if (!success) {
            println ("ERROR: Unable to evaluate array identifier (" + arrayExpr + ").")
            println (errStr + "\n" + this.mkErrorString(tree.head))
            return WalkControl.mkFailure()
          }

          // If the reference is to an object instead of an array, then re-pack that object's contained objects into an array
          var array:DynamicValue = array_
          if (array.isObject()) {
            val obj = array.getObject().get
            val containedObjects = obj.getContainedObjects()
            array = DynamicValue.mkArray(containedObjects.toArray)
          }

          if (!array.isArray()) {
            println ("ERROR: Type error for array identifier (" + arrayExpr + "), expected type " + DynamicValue.TYPE_OBJECT +", found type " + array.getTypeStr() + ". ")
            println (this.mkErrorString(tree.head))
            return WalkControl.mkFailure()
          }

          // Then, run the code
          for (iterObj <- array.getArray().get) {
            // Push on a new scope to the variable LUT for inside the loop
            scopedVariableLUT.push()

            // Assign iterator the value in the variable LUT
            scopedVariableLUT.set(varName, iterObj)

            // Run the code in this loop
            val result = this.walkOneStep(codeblock)

            // Pop off new scope from variable LUT
            scopedVariableLUT.pop()

            // Check for errors, returns, etc
            if (result.failed() || result.hasReturnValue()) {
              // Return
              return result
            }
          }

          return walkOneStep(tree.tail)
        }

        /*
         * Conditionals
         */
        case IfStatement(conditions) => {

          breakable {
            for (condition <- conditions) {
              condition.conditionalMode match {
                case IfStatementCondition.MODE_IF => {
                  val (returnValue, result, errorStr) = conditionalLogic(condition.conditionExpr.get, condition.trueBranch)
                  if (!result.success) {
                    println (errorStr + "\n" + this.mkErrorString(tree.head) )
                    return WalkControl.mkFailure()
                  }
                  if (result.hasReturnValue()) return result
                  //if (result.breakLoop) return result
                  //if (result.exit) return result
                  if (returnValue == true) break()
                }
                case IfStatementCondition.MODE_ELSEIF => {
                  val (returnValue, result, errorStr) = conditionalLogic(condition.conditionExpr.get, condition.trueBranch)
                  if (!result.success) {
                    println (errorStr + "\n" + this.mkErrorString(tree.head) )
                    return WalkControl.mkFailure()
                  }
                  if (result.hasReturnValue()) return result
                  //if (result.breakLoop) return result
                  //if (result.exit) return result
                  if (returnValue == true) break()
                }
                case IfStatementCondition.MODE_ELSE => {
                  // If we reach here, then run the else block
                  val result = walkOneStep(condition.trueBranch)              // Note, no error display here as there's no expression to check for errors (and any errors in statements should be caught by their respective calls)
                  if (!result.success) return WalkControl.mkFailure()
                  if (result.hasReturnValue()) return result
                  //if (result.breakLoop) return result
                  //if (result.exit) return result
                  break()
                }
              }
            }
          }

          // If we reach here, then the traversal through the conditional was successful.  Continue walking
          return walkOneStep(tree.tail)

        }

        case _ => {
          throw new RuntimeException ("ERROR: Unknown statement: " + tree.head.toString)
        }

      }

    } else {
      // No statements left to process

      // Return
      return WalkControl.mkSuccess()
    }

  }

}


object Interpreter {
  val DEFAULT_ROOT_OBJECT_NAME    = "env_root"
}
