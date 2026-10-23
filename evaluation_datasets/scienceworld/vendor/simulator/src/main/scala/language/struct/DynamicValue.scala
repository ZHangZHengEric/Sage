package language.struct

import language.model.ConditionalOperator
import language.struct

class DynamicValue(private var value:String = "", private var valueObj:Option[EnvObject] = None, private var valueArray:Option[Array[DynamicValue]] = None, private val staticTypeCast:Option[String] = None) {

  // Alternate constructors
  def this() = this(value = "", valueObj = None, valueArray = None, staticTypeCast = None)
  def this(str:String) = this(value = str, valueObj = None, valueArray = None, staticTypeCast = None)
  def this(doubleIn:Double) = this(value = doubleIn.toString, valueObj = None, valueArray = None, staticTypeCast = None)
  def this(intIn:Int) = this(value = intIn.toString, valueObj = None, valueArray = None, staticTypeCast = None)
  def this(boolIn:Boolean) = this(value = boolIn.toString, valueObj = None, valueArray = None, staticTypeCast = None)
  def this(objIn:EnvObject) = this(value = "", valueObj = Some(objIn), valueArray = None, staticTypeCast = None)
  def this(arrayIn:Array[DynamicValue]) = this(value = "", valueObj = None, valueArray = Some(arrayIn), staticTypeCast = None)


  /*
   * Setters
   */
  def setValue(in:String): Unit = {
    this.value = in
    this.valueObj = None
    this.valueArray = None
  }

  def setValue(in:Double): Unit = {
    this.value = in.toString
    this.valueObj = None
    this.valueArray = None
  }

  def setValue(in:Boolean): Unit = {
    this.value = in.toString
    this.valueObj = None
    this.valueArray = None
  }

  def setValue(in:EnvObject): Unit = {
    this.value = ""
    this.valueObj = Some(in)
    this.valueArray = None
  }

  def setValue(in:Array[DynamicValue]):Unit = {
    this.value = ""
    this.valueObj = None
    this.valueArray = Some(in)
  }

  /*
   * Getters
   */
  def getNumber():Option[Double] = {
    if (this.isNumber()) return Some(this.value.toDouble)
    // Otherwise
    return None
  }

  def getInt():Option[Int] = {
    if (this.isInt()) return Some(this.value.toDouble.toInt)
    // Otherwise
    return None
  }

  def getString():Option[String] = {
    if (this.isString()) return Some(this.value)
    // Otherwise
    return None
  }

  def getBoolean():Option[Boolean] = {
    if (this.isBoolean()) return Some(this.value.toBoolean)
    // Otherwise
    return None
  }

  def getObject():Option[EnvObject] = {
    if (this.isObject()) return this.valueObj
    // Otherwise
    return None
  }

  def getArray():Option[Array[DynamicValue]] = {
    if (this.isArray()) return this.valueArray
    // Otherwise
    return None
  }

  /*
   * Type checking
   */
  def isNumber():Boolean = {
    if (this.staticTypeCast.isDefined) {
      if (this.staticTypeCast.get == DynamicValue.TYPE_NUMBER) { return true } else { return false }
    }

    if (this.isArray()) return false
    if (this.isObject()) return false

    try {
      val out = value.toDouble
      return true
    } catch {
      case _:Throwable => return false
    }
  }

  // A special case of a Number
  def isInt():Boolean = {
    if (this.staticTypeCast.isDefined) {
      if (this.staticTypeCast.get != DynamicValue.TYPE_NUMBER) return false     // Tests only negative, as it might still be a static number but not an int
    }

    if (this.isArray()) return false
    if (this.isObject()) return false
    // Check to see if this value (cast to a double) is also an integer.
    if (value.toDouble % 1 == 0) return true
    // Otherwise
    return false
  }


  def isString():Boolean = {
    if (this.staticTypeCast.isDefined) {
      if (this.staticTypeCast.get == DynamicValue.TYPE_STRING) { return true } else { return false }
    }

    if (this.isArray()) return false
    if (this.isObject()) return false
    if (this.isBoolean()) return false
    return !this.isNumber()
  }

  def isBoolean():Boolean = {
    if (this.staticTypeCast.isDefined) {
      if (this.staticTypeCast.get == DynamicValue.TYPE_BOOLEAN) { return true } else { return false }
    }

    if (this.isArray()) return false
    if (this.isObject()) return false

    try {
      val out = value.toBoolean
      return true
    } catch {
      case _:Throwable => return false
    }
  }

  def isObject():Boolean = {
    if (this.staticTypeCast.isDefined) {
      if (this.staticTypeCast.get == DynamicValue.TYPE_OBJECT) { return true } else { return false }
    }

    if (this.isArray()) return false
    return this.valueObj.isDefined
  }

  def isArray():Boolean = {
    if (this.staticTypeCast.isDefined) {
      if (this.staticTypeCast.get == DynamicValue.TYPE_ARRAY) { return true } else { return false }
    }

    return this.valueArray.isDefined
  }


  def getTypeStr():String = {
    if (this.staticTypeCast.isDefined) return this.staticTypeCast.get     // If we've statically cast this as something else

    if (this.isNumber()) return DynamicValue.TYPE_NUMBER
    if (this.isBoolean()) return DynamicValue.TYPE_BOOLEAN
    if (this.isObject()) return DynamicValue.TYPE_OBJECT
    if (this.isString()) return DynamicValue.TYPE_STRING
    if (this.isArray()) return DynamicValue.TYPE_ARRAY
    // Otherwise (this should never happen)
    return DynamicValue.TYPE_UNKNOWN
  }

  def isSameType(that:DynamicValue):Boolean = {
    if (this.isNumber() && that.isNumber()) return true
    if (this.isString() && that.isString()) return true
    if (this.isBoolean() && that.isBoolean()) return true
    if (this.isObject() && that.isObject()) return true
    if (this.isArray() && that.isArray()) return true
    // Otherwise
    return false
  }


  /*
   * Operations
   */

  def add(that:DynamicValue):(DynamicValue, Boolean, String) = {
    // TODO: Allow adding strings and objects, typecasting down to String (and giving a basic string description of the object for debugging)?
    if (!this.isSameType(that)) return (new DynamicValue(), false, "Values are not the same type (" + this.getTypeStr() + ", " + that.getTypeStr() + ").")

    if (this.isNumber()) {
      val sum = this.getNumber().get + that.getNumber().get
      return (new DynamicValue(sum), true, "")
    } else if (this.isString()) {
      val concat = this.getString().get + that.getString().get
      return (new DynamicValue(concat), true, "")
    }

    // If we reach here, the types are not supported
    return (new DynamicValue(), false, "Addition is not defined on this type (" + this.getTypeStr() + ")")
  }

  def subtract(that:DynamicValue):(DynamicValue, Boolean, String) = {
    if (!this.isSameType(that)) return (new DynamicValue(), false, "Values are not the same type (" + this.getTypeStr() + ", " + that.getTypeStr() + ").")

    if (this.isNumber()) {
      val sub = this.getNumber().get - that.getNumber().get
      return (new DynamicValue(sub), true, "")
    }

    return (new DynamicValue(), false, "Subtraction is not defined on this type (" + this.getTypeStr() + ")")
  }

  def multiply(that:DynamicValue):(DynamicValue, Boolean, String) = {
    if (!this.isSameType(that)) return (new DynamicValue(), false, "Values are not the same type (" + this.getTypeStr() + ", " + that.getTypeStr() + ").")

    if (this.isNumber()) {
      val prod = this.getNumber().get * that.getNumber().get
      return (new DynamicValue(prod), true, "")
    }

    return (new DynamicValue(), false, "Multiplication is not defined on this type (" + this.getTypeStr() + ")")
  }

  def divide(that:DynamicValue):(DynamicValue, Boolean, String) = {
    if (!this.isSameType(that)) return (new DynamicValue(), false, "Values are not the same type (" + this.getTypeStr() + ", " + that.getTypeStr() + ").")

    if (this.isNumber()) {
      val div = this.getNumber().get / that.getNumber().get
      return (new DynamicValue(div), true, "")
    }

    return (new DynamicValue(), false, "Division is not defined on this type (" + this.getTypeStr() + ")")
  }

  def modulo(that:DynamicValue):(DynamicValue, Boolean, String) = {
    if (!this.isSameType(that)) return (new DynamicValue(), false, "Values are not the same type (" + this.getTypeStr() + ", " + that.getTypeStr() + ").")

    if (this.isNumber()) {
      val div = this.getNumber().get % that.getNumber().get
      return (new DynamicValue(div), true, "")
    }

    return (new DynamicValue(), false, "Modulo is not defined on this type (" + this.getTypeStr() + ")")
  }


  /*
   * Boolean operation (generic)
   */
  def booleanOperator(operator:String, that:DynamicValue):(Boolean, Boolean, String) = {      // (Success, evaluation result, errorString)
    // First, check that we're comparing the same types
    if (this.getTypeStr() != that.getTypeStr()) {
      var errorStr = "ERROR: Comparing expressions of different types (" + this.getTypeStr() + " vs " + that.getTypeStr() + ")."
      return (false, false, errorStr)
    }

    // Break out comparisons by type
    this.getTypeStr() match {
      case DynamicValue.TYPE_NUMBER => operator match {
        case ConditionalOperator.EQUALS => (true, this.getNumber().get == that.getNumber().get, "")
        case ConditionalOperator.NOTEQUALS => (true, this.getNumber().get != that.getNumber().get, "")
        case ConditionalOperator.LESSTHANEQ => (true, this.getNumber().get <= that.getNumber().get, "")
        case ConditionalOperator.GREATERTHANEQ => (true, this.getNumber().get >= that.getNumber().get, "")
        case ConditionalOperator.LESSTHAN => (true, this.getNumber().get < that.getNumber().get, "")
        case ConditionalOperator.GREATERTHAN => (true, this.getNumber().get > that.getNumber().get, "")
        case _ => (false, false, "ERROR: Operator (" + operator + ") not supported on type (" + this.getTypeStr() + ")." )
      }
      case DynamicValue.TYPE_STRING => operator match {
        case ConditionalOperator.EQUALS => (true, this.getString().get == that.getString().get, "")
        case ConditionalOperator.NOTEQUALS => (true, this.getString().get != that.getString().get, "")
        case _ => (false, false, "ERROR: Operator (" + operator + ") not supported on type (" + this.getTypeStr() + ")." )
      }
      case DynamicValue.TYPE_BOOLEAN => operator match {
        case ConditionalOperator.EQUALS => (true, this.getBoolean().get == that.getBoolean().get, "")
        case ConditionalOperator.NOTEQUALS => (true, this.getBoolean().get != that.getBoolean().get, "")
        case _ => (false, false, "ERROR: Operator (" + operator + ") not supported on type (" + this.getTypeStr() + ")." )
      }
      case DynamicValue.TYPE_OBJECT => operator match {
        case ConditionalOperator.EQUALS => (true, this.getObject().get == that.getObject().get, "")
        case ConditionalOperator.NOTEQUALS => (true, this.getObject().get != that.getObject().get, "")
        case ConditionalOperator.OBJ_IN => (true, that.getObject().get.contains( this.getObject().get ), "")      // 'x in y': checks if y contains x
        case _ => (false, false, "ERROR: Operator (" + operator + ") not supported on type (" + this.getTypeStr() + ")." )
      }
      // TODO: Array Equality/inequality/containment
      case DynamicValue.TYPE_ARRAY => operator match {
        case _ => (false, false, "ERROR: Operator (" + operator + ") not supported on type (" + this.getTypeStr() + ")." )
      }
      case _ => {
        return (false, false, "ERROR: Unknown type for boolean operations (" + this.getTypeStr() + "). ")
      }
    }

  }


  /*
   * Built in functions
   */

  // Mathematical functions
  def round():(Boolean, String, DynamicValue) = {    // (Success, ErrorString, Result)
    if (!this.isNumber()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_NUMBER + ", found: " + this.getTypeStr() + " [" + this.value + "]).", new DynamicValue())
    val result = new DynamicValue( math.round( this.getNumber().get ) )
    return (true, "", result)
  }

  def ceil():(Boolean, String, DynamicValue) = {    // (Success, ErrorString, Result)
    if (!this.isNumber()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_NUMBER + ", found: " + this.getTypeStr() + " [" + this.value + "]).", new DynamicValue())
    val result = new DynamicValue( math.ceil( this.getNumber().get ) )
    return (true, "", result)
  }

  def floor():(Boolean, String, DynamicValue) = {    // (Success, ErrorString, Result)
    if (!this.isNumber()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_NUMBER + ", found: " + this.getTypeStr() + " [" + this.value + "]).", new DynamicValue())
    val result = new DynamicValue( math.floor( this.getNumber().get ) )
    return (true, "", result)
  }

  def abs():(Boolean, String, DynamicValue) = {    // (Success, ErrorString, Result)
    if (!this.isNumber()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_NUMBER + ", found: " + this.getTypeStr() + " [" + this.value + "]).", new DynamicValue())
    val result = new DynamicValue( math.abs( this.getNumber().get ) )
    return (true, "", result)
  }


  /*
   * Build in functions (Type Casting)
   */
  def str():(Boolean, String, DynamicValue) = {    // (Success, ErrorString, Result)
    if (this.isObject()) {
      return (true, "", new DynamicValue(value = this.valueObj.get.toString(), staticTypeCast = Some(DynamicValue.TYPE_STRING)))
    } else if (this.isArray()) {
      return (true, "", new DynamicValue(value = this.toString(), staticTypeCast = Some(DynamicValue.TYPE_STRING)))
    } else {
      return (true, "", new DynamicValue( value = this.value, staticTypeCast = Some(DynamicValue.TYPE_STRING)) )
    }
  }

  /*
   * Built in functions (Array functions)
   */
  def size():(Boolean, String, DynamicValue) = {
    if (!this.isArray()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_ARRAY + ", found: " + this.getTypeStr() + " [" + this.value + "]).", new DynamicValue())
    val result = new DynamicValue( this.getArray().get.length )
    return (true, "", result)
  }

  def isEmpty():(Boolean, String, DynamicValue) = {
    if (!this.isArray()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_ARRAY + ", found: " + this.getTypeStr() + " [" + this.value + "]).", new DynamicValue())
    val result = new DynamicValue( this.getArray().get.isEmpty )
    return (true, "", result)
  }

  // Get element of array
  def getElem(elemIdx:Int):(Boolean, String, DynamicValue) = {
    if (!this.isArray()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_ARRAY + ", found: " + this.getTypeStr() + " [" + this.value + "]).", new DynamicValue())
    val array = this.getArray.get
    val size = array.length
    if (elemIdx >= size) return (false, "ERROR: Requested array index (" + elemIdx + ") is greater or equal to the length of the array (" + size + ").", new DynamicValue())
    if (elemIdx < 0) return (false, "ERROR: Requested array index (" + elemIdx + ") is less than zero.", new DynamicValue())
    val elem = array(elemIdx)
    return (true, "", elem)
  }

  def getElem(elemIdx:DynamicValue):(Boolean, String, DynamicValue) = {
    if (!elemIdx.isInt()) return (false, "ERROR: Type error (expected integer index, found: " + this.getTypeStr() + " [" + this.value + "]).", new DynamicValue())
    return this.getElem(elemIdx.getInt().get)
  }

  // Set element of array
  def setElem(elemIdx:Int, value:DynamicValue):(Boolean, String) = {
    if (!this.isArray()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_ARRAY + ", found: " + this.getTypeStr() + " [" + this.value + "]).")
    val array = this.getArray.get
    val size = array.length
    if (elemIdx >= size) return (false, "ERROR: Requested array index (" + elemIdx + ") is greater or equal to the length of the array (" + size + ").")
    if (elemIdx < 0) return (false, "ERROR: Requested array index (" + elemIdx + ") is less than zero.")

    // Set the array element
    array(elemIdx) = value
    this.setValue(array)
    return (true, "")
  }

  def setElem(elemIdx:DynamicValue, value:DynamicValue):(Boolean, String) = {
    if (!elemIdx.isInt()) return (false, "ERROR: Type error (expected integer index, found: " + this.getTypeStr() + " [" + this.value + "]).")
    return this.setElem(elemIdx.getInt().get, value)
  }

  // Add an element to the end of the array
  def appendElem(value:DynamicValue):(Boolean, String) = {
    if (!this.isArray()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_ARRAY + ", found: " + this.getTypeStr() + " [" + this.value + "]).")
    val newArray = this.getArray().get ++ Array(value)
    this.setValue(newArray)
    return (true, "")
  }

  // Remove an element from an array
  def removeElem(elemIdx:Int):(Boolean, String) = {
    if (!this.isArray()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_ARRAY + ", found: " + this.getTypeStr() + " [" + this.value + "]).")
    val array = this.getArray.get
    val size = array.length
    if (elemIdx >= size) return (false, "ERROR: Requested array index (" + elemIdx + ") is greater or equal to the length of the array (" + size + ").")
    if (elemIdx < 0) return (false, "ERROR: Requested array index (" + elemIdx + ") is less than zero.")

    // Set the array element
    val currentArray = this.getArray().get
    val newArray = currentArray.slice(0, elemIdx) ++ currentArray.slice(elemIdx+1, currentArray.length)
    this.setValue(newArray)
    return (true, "")
  }

  def removeElem(elemIdx:DynamicValue):(Boolean, String) = {
    if (!elemIdx.isInt()) return (false, "ERROR: Type error (expected integer index, found: " + this.getTypeStr() + " [" + this.value + "]).")
    return this.removeElem(elemIdx.getInt().get)
  }



  /*
   * String methods
   */
  override def toString():String = {
    if (this.isNumber()) return this.getNumber().get.toString()
    if (this.isString()) return this.getString().get.toString()
    if (this.isBoolean()) return this.getBoolean().get.toString()
    if (this.isObject()) return this.getObject().get.toString()
    if (this.isArray()) return ("Array(" + this.getArray().get.mkString(", ") + ")")

    // Otherwise
    return "ERROR: toString(): Unknown object type. "
  }
}


object DynamicValue {
  val TYPE_NUMBER   =   "number"
  val TYPE_STRING   =   "string"
  val TYPE_BOOLEAN  =   "boolean"
  val TYPE_OBJECT   =   "object"
  val TYPE_ARRAY    =   "array"
  val TYPE_UNKNOWN  =   "unknown"


  /*
   * Built-in Functions
   */
  // Mathematical functions
  def min(args:Array[DynamicValue]):(Boolean, String, DynamicValue) = {
    // Type check
    for (arg <- args) {
      if (!arg.isNumber()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_NUMBER + ", found: " + arg.getTypeStr() + " [" + arg.value + "]).", new DynamicValue())
    }
    // Operation
    var curMin = args(0)
    for (arg <- args) {
      if (arg.getNumber().get < curMin.getNumber().get) curMin = arg
    }
    // Return
    return (true, "", curMin)
  }

  def max(args:Array[DynamicValue]):(Boolean, String, DynamicValue) = {
    // Type check
    for (arg <- args) {
      if (!arg.isNumber()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_NUMBER + ", found: " + arg.getTypeStr() + " [" + arg.value + "]).", new DynamicValue())
    }
    // Operation
    var curMax = args(0)
    for (arg <- args) {
      if (arg.getNumber().get > curMax.getNumber().get) curMax = arg
    }
    // Return
    return (true, "", curMax)
  }

  def exp(arg:DynamicValue):(Boolean, String, DynamicValue) = {
    // Type check
    if (!arg.isNumber()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_NUMBER + ", found: " + arg.getTypeStr() + " [" + arg.value + "]).", new DynamicValue())
    // Operation
    val result = new DynamicValue( math.exp( arg.getNumber().get ) )
    // Return
    return (true, "", result)
  }

  def sqrt(arg:DynamicValue):(Boolean, String, DynamicValue) = {
    // Type check
    if (!arg.isNumber()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_NUMBER + ", found: " + arg.getTypeStr() + " [" + arg.value + "]).", new DynamicValue())
    // Operation
    val result = new DynamicValue( math.sqrt( arg.getNumber().get ) )
    // Return
    return (true, "", result)
  }

  def log10(arg:DynamicValue):(Boolean, String, DynamicValue) = {
    // Type check
    if (!arg.isNumber()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_NUMBER + ", found: " + arg.getTypeStr() + " [" + arg.value + "]).", new DynamicValue())
    // Operation
    val result = new DynamicValue( math.log10( arg.getNumber().get ) )
    // Return
    return (true, "", result)
  }

  def pow(arg1:DynamicValue, arg2:DynamicValue):(Boolean, String, DynamicValue) = {
    // Type check
    if (!arg1.isNumber()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_NUMBER + ", found: " + arg1.getTypeStr() + " [" + arg1.value + "]).", new DynamicValue())
    if (!arg2.isNumber()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_NUMBER + ", found: " + arg2.getTypeStr() + " [" + arg2.value + "]).", new DynamicValue())
    // Operation
    val result = new DynamicValue( math.pow( arg1.getNumber().get, arg2.getNumber().get ) )
    // Return
    return (true, "", result)
  }

  // Trigonometry
  def sin(arg:DynamicValue):(Boolean, String, DynamicValue) = {
    // Type check
    if (!arg.isNumber()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_NUMBER + ", found: " + arg.getTypeStr() + " [" + arg.value + "]).", new DynamicValue())
    // Operation
    val result = new DynamicValue( math.sin( arg.getNumber().get ) )
    // Return
    return (true, "", result)
  }

  def cos(arg:DynamicValue):(Boolean, String, DynamicValue) = {
    // Type check
    if (!arg.isNumber()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_NUMBER + ", found: " + arg.getTypeStr() + " [" + arg.value + "]).", new DynamicValue())
    // Operation
    val result = new DynamicValue( math.cos( arg.getNumber().get ) )
    // Return
    return (true, "", result)
  }

  def tan(arg:DynamicValue):(Boolean, String, DynamicValue) = {
    // Type check
    if (!arg.isNumber()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_NUMBER + ", found: " + arg.getTypeStr() + " [" + arg.value + "]).", new DynamicValue())
    // Operation
    val result = new DynamicValue( math.tan( arg.getNumber().get ) )
    // Return
    return (true, "", result)
  }

  def asin(arg:DynamicValue):(Boolean, String, DynamicValue) = {
    // Type check
    if (!arg.isNumber()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_NUMBER + ", found: " + arg.getTypeStr() + " [" + arg.value + "]).", new DynamicValue())
    // Operation
    val result = new DynamicValue( math.asin( arg.getNumber().get ) )
    // Return
    return (true, "", result)
  }

  def acos(arg:DynamicValue):(Boolean, String, DynamicValue) = {
    // Type check
    if (!arg.isNumber()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_NUMBER + ", found: " + arg.getTypeStr() + " [" + arg.value + "]).", new DynamicValue())
    // Operation
    val result = new DynamicValue( math.acos( arg.getNumber().get ) )
    // Return
    return (true, "", result)
  }

  def atan(arg:DynamicValue):(Boolean, String, DynamicValue) = {
    // Type check
    if (!arg.isNumber()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_NUMBER + ", found: " + arg.getTypeStr() + " [" + arg.value + "]).", new DynamicValue())
    // Operation
    val result = new DynamicValue( math.atan( arg.getNumber().get ) )
    // Return
    return (true, "", result)
  }

  /*
   * Object properties
   */
  // Check if an object has a given property
  def hasProperty(argObj:DynamicValue, propName:DynamicValue):(Boolean, String, DynamicValue) = {
    // Type check
    if (!argObj.isObject()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_OBJECT + ", found: " + argObj.getTypeStr() + " [" + argObj.value + "]).", new DynamicValue())
    if (!propName.isString()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_STRING + ", found: " + propName.getTypeStr() + " [" + propName.value + "]).", new DynamicValue())
    // Operation
    val obj = argObj.getObject().get
    val propNameStr = propName.getString().get
    val result = new DynamicValue( obj.hasProperty(propNameStr) )
    // Return
    return (true, "", result)
  }

  /*
   * Array functions
   */
  // Arg1: Array, arg2: The element of the array being searched for
  def contains(arg1:DynamicValue, arg2:DynamicValue):(Boolean, String, DynamicValue) = {
    // Type check
    if (!arg1.isArray()) return (false, "ERROR: Type error (expected " + DynamicValue.TYPE_ARRAY + ", found: " + arg1.getTypeStr() + " [" + arg1.value + "]).", new DynamicValue())
    // Operation
    for (elem <- arg1.getArray().get) {
      // TODO: Check equality
      val (success, result, errStr) = elem.booleanOperator(ConditionalOperator.EQUALS, arg2)
      if (result == true) return (true, "", new DynamicValue(true))
    }
    // Return
    return (true, "", new DynamicValue(false))
  }

  /*
   * Array generators
   */
  def mkArray(in:Array[Int]):DynamicValue = {
    val out = new Array[DynamicValue](in.size)
    for (i <- 0 until in.length) {
      out(i) = new DynamicValue(in(i))
    }
    return new DynamicValue(out)
  }

  def mkArray(in:Array[Double]):DynamicValue = {
    val out = new Array[DynamicValue](in.size)
    for (i <- 0 until in.length) {
      out(i) = new DynamicValue(in(i))
    }
    return new DynamicValue(out)
  }

  def mkArray(in:Array[String]):DynamicValue = {
    val out = new Array[DynamicValue](in.size)
    for (i <- 0 until in.length) {
      out(i) = new DynamicValue(in(i))
    }
    return new DynamicValue(out)
  }

  def mkArray(in:Array[Boolean]):DynamicValue = {
    val out = new Array[DynamicValue](in.size)
    for (i <- 0 until in.length) {
      out(i) = new DynamicValue(in(i))
    }
    return new DynamicValue(out)
  }

  def mkArray(in:Array[EnvObject]):DynamicValue = {
    val out = new Array[DynamicValue](in.size)
    for (i <- 0 until in.length) {
      out(i) = new DynamicValue(in(i))
    }
    return new DynamicValue(out)
  }


  /*
   * Main
   */
  def main(args:Array[String]) = {
    // Quick tests
    val intArray = Array(1, 2, 3, 4, 5)
    val dynamicArray1 = this.mkArray(intArray)
    println (dynamicArray1.toString())
    println (dynamicArray1.getTypeStr())

    val doubleArray = Array(1.2, 2.3, 3.4, 4.5, 5.6)
    val dynamicArray2 = this.mkArray(doubleArray)
    println (dynamicArray2.toString())
    println (dynamicArray2.getTypeStr())

    val strArray = Array("a", "b", "c", "d", "e")
    val dynamicArray3 = this.mkArray(strArray)
    println (dynamicArray3.toString())
    println (dynamicArray3.getTypeStr())

    val boolArray = Array(true, false, true, true, false)
    val dynamicArray4 = this.mkArray(boolArray)
    println (dynamicArray4.toString())
    println (dynamicArray4.getTypeStr())

    val obj1 = new EnvObject()
    obj1.setProperty("name", new DynamicValue("obj1"))
    val obj2 = new EnvObject()
    obj2.setProperty("num", new DynamicValue(1.23))
    val obj3 = new EnvObject()
    obj3.setProperty("bool", new DynamicValue(true))
    val objArray = Array(obj1, obj2, obj3)
    val dynamicArray5 = this.mkArray(objArray)
    println (dynamicArray5.toString())
    println (dynamicArray5.getTypeStr())
    println (dynamicArray5.size())

    println (DynamicValue.contains(dynamicArray5, new DynamicValue(obj1)) )
    println (DynamicValue.contains(dynamicArray5, new DynamicValue(new EnvObject())) )
  }

}
