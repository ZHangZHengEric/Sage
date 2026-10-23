package language.struct

import language.model.Str

import scala.collection.mutable
import scala.collection.mutable.ArrayBuffer
import scala.util.control.Breaks._

/*
 * Storage class for a variable value look-up-table (LUT)
 */

class ScopedVariableLUT {
  val scopes = new ArrayBuffer[VariableLUT]()
  // Initialization
  this.push()

  /*
   * Scoping
   */
  def push(): Unit = {
    scopes.append( new VariableLUT() )
  }

  def pop(): Unit = {
    if (scopes.size == 1) throw new RuntimeException("ScopedVariableLUT: ERROR: pop() called when there are no more scopes to pop -- only global scope remains. ")
    scopes.remove( scopes.length-1, 1 )
  }

  /*
   * Accessors
   */

  def contains(name:String):Boolean = {
    for (scope <- scopes) if (scope.contains(name)) return true
    // Otherwise
    return false
  }

  def variableNames():Array[String] = {
    val out = new ArrayBuffer[String]()
    for (scope <- scopes) {
      out.insertAll(out.length, scope.variableNames())
    }
    // Return
    out.toArray
  }

  def get(name:String):Option[DynamicValue] = {
    for (i <- scopes.length-1 to 0 by -1) {
      if (scopes(i).contains(name)) return scopes(i).get(name)
    }
    // Otherwise
    return None
  }

  def set(name:String, value:DynamicValue) = {
    breakable {
      for (i <- scopes.length-1 to 0 by -1) {
        if (scopes(i).contains(name)) {
          scopes(i).set(name, value)
          break
        }
      }
      // If we reach here, the variable is new
      scopes.last.set(name, value)
    }
  }

  /*
   * String methods
   */
  override def toString():String = {
    val os = new StringBuilder
    for (i <- 0 until scopes.length) {
      os.append("Scope " + i + ":\n")
      os.append( scopes(i).toString() )
    }
    os.toString()
  }

}

object ScopedVariableLUT {

  // Test
  def main(args:Array[String]): Unit = {
    val scopedLUT = new ScopedVariableLUT()

    scopedLUT.set("globalTest1", new DynamicValue("123"))
    scopedLUT.set("globalTest2", new DynamicValue("456"))

    scopedLUT.push()
    scopedLUT.set("scope2Test1", new DynamicValue("ABC"))
    scopedLUT.set("scope2Test2", new DynamicValue("DEF"))

    scopedLUT.push()
    scopedLUT.set("scope3Test1", new DynamicValue("xyz"))
    scopedLUT.set("scope3Test2", new DynamicValue("wyx"))

    scopedLUT.set("globalTest1", new DynamicValue("-1-"))
    scopedLUT.set("scope2Test1", new DynamicValue("-2-"))
    scopedLUT.set("scope3Test1", new DynamicValue("-3-"))


    println( scopedLUT.toString() )

    println ( scopedLUT.get("globalTest1") )
    println ( scopedLUT.get("globalTest2") )
    println ( scopedLUT.get("scope2Test1") )
    println ( scopedLUT.get("scope2Test2") )
    println ( scopedLUT.get("scope3Test1") )
    println ( scopedLUT.get("scope3Test2") )

    println ("----------------------")
    println ("after pop:")

    scopedLUT.pop()
    println( scopedLUT.toString() )

    println ( scopedLUT.get("globalTest1") )
    println ( scopedLUT.get("globalTest2") )
    println ( scopedLUT.get("scope2Test1") )
    println ( scopedLUT.get("scope2Test2") )
    println ( scopedLUT.get("scope3Test1") )
    println ( scopedLUT.get("scope3Test2") )

    println ("----------------------")
    println ("after pop:")

    scopedLUT.pop()
    println( scopedLUT.toString() )

    println ( scopedLUT.get("globalTest1") )
    println ( scopedLUT.get("globalTest2") )
    println ( scopedLUT.get("scope2Test1") )
    println ( scopedLUT.get("scope2Test2") )
    println ( scopedLUT.get("scope3Test1") )
    println ( scopedLUT.get("scope3Test2") )


    println ("----------------------")
    println ("after pop (should fail):")

    scopedLUT.pop()   // Should fail



  }

}


class VariableLUT {
  val lut = mutable.Map[String, DynamicValue]()

  def contains(name:String):Boolean = {
    return lut.contains(name)
  }

  def variableNames():Array[String] = {
    return lut.keySet.toArray
  }

  def get(name:String):Option[DynamicValue] = {
    return lut.get(name)
  }

  def set(name:String, value:DynamicValue) = {
    lut(name) = value
  }

  /*
   * String methods
   */
  override def toString():String = {
    val os = new mutable.StringBuilder()

    for (varName <- this.variableNames().sorted) {
      val value = this.get(varName).toString
      val sanitizedValue = Str.desanitizeStrControlChars(value)
      os.append(" " + varName.formatted("%20s") + "\t" + sanitizedValue + "\n")
    }

    // Return
    os.toString()
  }
}
