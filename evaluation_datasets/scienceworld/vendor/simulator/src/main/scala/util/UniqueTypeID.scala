package util

import java.io.PrintWriter

import scala.collection.mutable
import scala.collection.mutable.ArrayBuffer


/*
 * Generate unique object IDs for object types
 */

object UniqueTypeID {
  val FILENAME_IDS = "object_type_ids.tsv"
  val lut = this.load(FILENAME_IDS)
  var nextID:Long = lut.size

  // Get an ID from the look-up-table
  def getID(key:String):Long = {
    // Case 1: Existing ID
    if (lut.contains(key)) return lut(key)

    // Case 2: Add new
    return this.add(key)
  }

  // Get the type string for a given ID
  def getTypeStr(id:Long):String = {
    for (key <- lut.keySet) {
      if (lut(key) == id) return key
    }
    // If we reach here, key was not found
    return ""
  }

  // Add an element to the look-up-table
  def add(name:String): Long = {
    lut(name) = this.nextID
    this.nextID += 1

    this.save(FILENAME_IDS)

    return this.getID(name)
  }

  // Save look-up-table
  def save(filename:String): Unit = {
    val pw = new PrintWriter(filename)

    for (key <- this.lut.keySet.toArray.sorted) {
      pw.println(key + "\t" + this.lut(key))
    }

    pw.flush()
    pw.close()
  }

  // Load look-up-table
  def load(filename:String):mutable.HashMap[String, Long] = {
    val out = mutable.HashMap[String, Long]()

    try {
      for (line <- io.Source.fromFile(filename, "UTF-8").getLines()) {
        val fields = line.split("\t")
        if (fields.length == 2) {
          val key = fields(0)
          val value = fields(1).toLong
          out(key) = value
        }
      }
    } catch {
      case e:Throwable => {
        println ("WARNING: Unable to load type-id look-up-table (" + FILENAME_IDS + ").  Creating a new one. ")
      }
    }

    return out
  }

  // Dump the look-up-table to a JSON dictionary
  def toJSON():String = {
    val elements = new ArrayBuffer[String]
    for (key <- this.lut.keySet.toArray.sorted) {
      val str = "\"" + key + "\":" + this.lut(key)
      elements.append(str)
    }

    val jsonOut = "{" + elements.mkString(", ") + "}"
    return jsonOut
  }

}
