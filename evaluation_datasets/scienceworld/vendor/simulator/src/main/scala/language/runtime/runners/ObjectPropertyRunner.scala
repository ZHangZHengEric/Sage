package language.runtime.runners

import language.model.{ClassDef, PropertyFunction}
import language.runtime.Interpreter
import language.struct.{DynamicValue, EnvObject, ScopedVariableLUT, Taxonomy}

import scala.collection.mutable
import scala.util.control.Breaks._


class ObjectPropertyRunner {

}

object ObjectPropertyRunner {

  // This function runs all the property functions in the objects
  def populateRunnableProperties(objTreeRoot: EnvObject, classDefsLUT: Map[String, ClassDef], taxonomy: Taxonomy, fauxInterpreter: Interpreter) {
    val allObjects = PredicateRunner.collectObjects(objTreeRoot)

    //println ("* populateRunnableProperties(): Started... ")
    // For each object
    for (obj <- allObjects) {
      //println ("Obj: " + obj.toString())
      breakable {
        val objType = obj.getType()

        // Get the class definition
        if (!classDefsLUT.contains(objType)) {
          if (objType == Interpreter.DEFAULT_ROOT_OBJECT_NAME) {
            // Skip over this object type if it's the default object tree root type, AND doesn't appear to have any additional definition in the code
            break()
          } else if (objType == "Any") {
            // Special case -- Any shouldn't have a definition -- break
            break()
          }
          println("ERROR: Found object of type (" + objType + "), but there is no class definition for type (" + objType + ")\n")
          println(obj.toString())
          sys.exit(1)
        }
        val classDef = classDefsLUT(objType)
        val propFunctions = classDef.propertyFunctions

        // For each property function
        for (propFunction <- propFunctions) {
          this.runPropertyFunction(obj, propFunction, fauxInterpreter, objTreeRoot, classDefsLUT)
        }
      }
    }
  }

  // Run a single property function in a single object
  //def runPropertyFunction(obj:EnvObject, propName:String, fauxInterpreter:Interpreter, objTreeRoot: EnvObject, classDefLUT:Map[String, ClassDef]): (Boolean, String) = {
  def runPropertyFunction(obj:EnvObject, propFunction:PropertyFunction, fauxInterpreter:Interpreter, objTreeRoot: EnvObject, classDefLUT:Map[String, ClassDef]): (Boolean, String) = {
    // Step 1: Get class/property function
    val className = obj.getType()
    if (!classDefLUT.contains(className)) return (false, "ERROR: Unable to find class (" + className + ") specified in object type.\n" + obj.toString())
    val classDef = classDefLUT(className)
    val propName = propFunction.propName

    val codeblock = propFunction.codeblock

    // Step 2: Run the property function
    // Reset interpreter between runs
    fauxInterpreter.setRunPropertyFunctions( propFunction.calculateAtRuntime )      // Run subsequent object property references when called, or lookup store values?
    fauxInterpreter.setObjectTreeRoot(objTreeRoot)        // Reset object tree root (just in case it changes?)
    val propFunctVarLUT = new ScopedVariableLUT()
    propFunctVarLUT.set("this", new DynamicValue(obj))    // Create variable LUT with reference to "this" object
    fauxInterpreter.setVariableLUT(propFunctVarLUT)       // Reset interpreter with blank Variable LUT ( + reference to "this" )
    // Run interpreter
    val result = fauxInterpreter.walkOneStep(codeblock)
    if (result.failed()) {
      println("Interpreter exited with error while running property function (" + propName + ") for object type (" + className + ") on the specific object:\n" + obj.toString())
      sys.exit(1)
    }
    fauxInterpreter.setRunPropertyFunctions(false)        // Reset to disabled (normal)

    // Check for a valid return statement after execution is completed
    if (!result.hasReturnValue()) {
      println("ERROR: Property function (" + propName + ") for object type (" + className + ") does not appear to have generated a return value.")
      if (!codeblock.isEmpty) {
        // If a codeblock is present, display that line
        println("Around line " + codeblock.last.pos.line + ":\n " + codeblock.last.pos.longString)
      } else {
        // If no codeblock is present, just give the line number of the class definition to the user
        println("Around line " + classDef.pos)
      }
      sys.exit(1)
    }

    // Set the object's property to be that return type
    obj.setProperty(propName, result.returnValue.get)

    return (true, "")
  }


  // Create a look-up-table (LUT) that goes between className and the classDefinition
  def mkClassDefLUT(in:Option[List[ClassDef]]): Map[String, ClassDef] = {
    val out = mutable.Map[String, ClassDef]()
    if (in.isEmpty) return out.toMap

    for (classDef <- in.get) {
      out(classDef.name) = classDef
    }

    // return
    out.toMap
  }

}
