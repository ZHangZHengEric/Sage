package language.struct

import language.model.{ParamSig, ParamSigList, PredicateDef}
import language.runtime.runners.PredicateRunner

import scala.collection.mutable
import scala.collection.mutable.ArrayBuffer
import scala.util.control.Breaks.{break, breakable}


class ParamIterator(paramSigList:ParamSigList, objsByType:Map[String, Set[EnvObject]]) {

  var isCompleted:Boolean = false       // Have the maximum number of iterations completed?
  var isValid:Boolean = true            // Is the iterator valid to begin with (e.g. at least one object can potentially fill each parameter)

  val numParam = paramSigList.parameters.length
  val possibleFillers = this.findPossibleFillers()
  val duplicateParamTypes = this.getDuplicates( this.getObjTypes() )

  val out = Array.fill[Int](numParam)(0)
  val outObj = new Array[EnvObject](numParam)
  val maxValues = new Array[Int](numParam)
  for (i <- 0 until possibleFillers.length) {
    maxValues(i) = possibleFillers(i).length
    if (possibleFillers(i).length <= 0) {
      isValid = false
      isCompleted = false
    }
  }
  var count:Long = 0
  var countValid:Long = 0
  var countInvalid:Long = 0
  val size:Long = this.calculateSize()


  /*
  println ("##DEBUG##")
  println ("Parameters: " + predicate.paramSigList.toString())
  println ("Possible fillers:")
  for (i <- 0 until numParam) {
    println ("Slot " + i + ": " + possibleFillers(i).toList)
  }
  println ("maxValues: " + maxValues.toList)
  println ("out: " + out.toList)
   */


  /*
   * Iterator functions
   */
  // Returns true if there are additional combinations to iterate through.  Note, this is only approximate, and doesn't take duplicates into account (which are filtered by next())
  def hasNext():Boolean = {
    if (!this.isValid) return false         // Return false if the conditions are invalid (e.g. no objects of a given type to fill the slots)
    if (count < size) return true
    // Return
    false
  }

  // Retrieve the next pattern
  def next():Option[Array[EnvObject]] = {
    if (!this.hasNext()) return None

    breakable {
      while (this.hasNext()) {              // Break if we run out of iterations
        increment()
        count += 1
        this.convertCountToObjs()

        if (this.checkIfValid()) break      // Break after generating a valid pattern
        this.countInvalid += 1
        //println("Duplicates found...")
      }
    }

    if (!this.checkIfValid()) return None   // Return None if the sequence isn't valid

    // Otherwise, the sequence is valid
    this.countValid += 1
    return Some(this.outObj)
  }

  // Increment the pattern
  private def increment(): Unit = {
    if (count >= size) return

    breakable {
      for (i <- (numParam-1) to 0 by -1) {
        //println ("i: " + i)
        //println ("out: " + out.toList)
        //println ("maxValues: " + maxValues.toList)
        if ( out(i) < (maxValues(i)-1) ) {
          out(i) += 1
          break()
        } else {
          out(i) = 0
        }
      }
      // If we reach here, then there are no more patterns to iterate through
      //isComplete = true
    }
  }


  // Approximate, doesn't take duplicates into account
  private def calculateSize():Long = {
    var sum:Long = 1
    for (i <- 0 until numParam) {
      sum *= maxValues(i)
    }
    // Return
    sum
  }

  // Convert from indices in 'out' to object references in 'outObj'
  private def convertCountToObjs(): Unit = {
    for (i <- 0 until numParam) {
      outObj(i) = this.possibleFillers(i)(out(i))
    }
  }


  private def getObjTypes():Array[String] = {
    val out = new ArrayBuffer[String]
    for (param <- paramSigList.parameters) {
      out.append( param.objType )
    }
    return out.toArray
  }

  // Look through the list of parameters for parameters that contain the same types (e.g. two or more are of type 'Animal'). Store the type as the key in the hashmap,
  // and the indices of the duplicates as values in a Set, so we can check them quickly later.
  private def getDuplicates(paramTypes:Array[String]):Map[String, mutable.Set[Int]] = {
    val out = mutable.Map[String, mutable.Set[Int]]()
    val dups = paramTypes.groupBy(identity).collect { case (x,ys) if ys.lengthCompare(1) > 0 => x }

    for (dupType <- dups) {
      for (i <- 0 until paramSigList.parameters.length) {
        if (paramSigList.parameters(i).objType == dupType) {
          if (!out.contains(dupType)) out(dupType) = mutable.Set[Int]()
          out(dupType).add(i)
        }
      }
    }

    return out.toMap
  }

  // Checks if the current value in the iterator is valid (if it's invalid, it likely contains duplicates)
  private def checkIfValid():Boolean = {
    //println ("* checkIfValid(): Started... ")
    if (this.duplicateParamTypes.size == 0) {
      //println("\tNo Duplicates -- exiting")
      return true
    }

    for (objKey <- this.duplicateParamTypes.keySet) {
      val objUUIDs = mutable.Set[Long]()
      for (idx <- this.duplicateParamTypes(objKey)) {
        val obj = this.outObj(idx)
        val uuid = obj.uuid
        if (objUUIDs.contains(uuid)) return false     // Found a duplicate
        objUUIDs.add(uuid)
      }
    }

    // Otherwise, if we reach here, no duplicates were found
    return true
  }



  /*
   * Get fillers for each parameter
   */
  // Find a list of objects that might fill a single parameter.
  def findPossibleFillers():Array[Array[EnvObject]] = {
    val out = new Array[Array[EnvObject]](this.numParam)
    for (i <- 0 until this.numParam) {
      val parameter = paramSigList.parameters(i)
      val paramName = parameter.name
      val paramType = parameter.objType
      if (objsByType.contains(paramType)) {
        out(i) = objsByType(paramType).toArray.sortBy(_.uuid)
      } else {
        out(i) = Array.empty[EnvObject]
      }
      //println ("Found " + out(i).size + " of type " + paramType)
    }

    return out
  }




}

object ParamIterator {


  def main(args:Array[String]): Unit = {
    // Step 1: Create faux object tree
    val objTreeRoot = new EnvObject()
    objTreeRoot.setName("root")

    val obj1 = new EnvObject
    val obj2 = new EnvObject
    val obj3 = new EnvObject
    val obj4 = new EnvObject
    val obj5 = new EnvObject
    val obj6 = new EnvObject
    obj1.setName("obj1")
    obj2.setName("obj2")
    obj3.setName("obj3")
    obj4.setName("obj4")
    obj5.setName("obj5")
    obj6.setName("obj6")
    obj1.setType("type1")
    obj2.setType("type1")
    obj3.setType("type2")
    obj4.setType("type1")
    obj5.setType("type2")
    obj6.setType("type3")
    objTreeRoot.addObject(obj1)
    objTreeRoot.addObject(obj2)
    objTreeRoot.addObject(obj3)
    objTreeRoot.addObject(obj4)
    objTreeRoot.addObject(obj5)
    objTreeRoot.addObject(obj6)


    // Step 2: Collect objects
    val objsByType = PredicateRunner.collectObjectsByType(objTreeRoot, new Taxonomy(""))

    // Step 3: Create faux parameter
    val param1 = new ParamSig("param1", "type1")
    val param2 = new ParamSig("param2", "type3")
    val param3 = new ParamSig("param3", "type1")
    val param4 = new ParamSig("param1", "type2")
    val paramSigList = new ParamSigList( List(param1, param2, param3, param4) )
    //val paramSigList = new ParamSigList( List(param1) )
    //val paramSigList = new ParamSigList( List(param1, param3) )
    val predDef = new PredicateDef("testPredicate", paramSigList, None, None, None)


    // Step 4: Test Iterator
    val iter = new ParamIterator(predDef.paramSigList, objsByType)

    while (iter.hasNext()) {
      val combo = iter.next()
      println(iter.count + "\t" + iter.countValid + "\t" + iter.countInvalid)

      if (combo.isDefined) {
        for (i <- 0 until combo.get.length) {
          println("\tParam " + i + ": " + combo.get(i).toString())
        }
        println("")
      }
    }



  }


}
