package util

import scienceworld.objects.portal.Portal
import scienceworld.struct.EnvObject
import scienceworld.struct.EnvObject._

import scala.collection.mutable.ArrayBuffer

object StringHelpers {

  def objectListToStringDescription(objs:Set[EnvObject], perspectiveContainer:EnvObject, mode:Int = MODE_CURSORY_DETAIL, multiline:Boolean = false):String = {
    // Collect object descriptions
    val filteredObjDescs = new ArrayBuffer[String]
    for (obj <- objs.toList.sortBy(obj => (obj.name, obj.uuid))) {
      obj match {
        case x:Portal => {
          val desc = x.getDescriptionSafe(mode, perspectiveContainer)
          if (desc.isDefined) filteredObjDescs.append(desc.get)
        }
        case x:EnvObject => {
          val desc = x.getDescriptionSafe(mode)
          if (desc.isDefined) filteredObjDescs.append(desc.get)
        }
      }
    }

    // No contents
    if (filteredObjDescs.size == 0) {
      if (multiline) return "\tnothing"
      return "nothing"
    }

    // Single line
    if (!multiline) return filteredObjDescs.mkString(", ")

    // Multi-line
    val os = new StringBuilder
    for (desc <- filteredObjDescs) {
      os.append("\t" + desc + "\n")
    }

    return os.toString
  }


  def portalListToStringDescription(objs:Set[Portal], perspectiveContainer:EnvObject, mode:Int = MODE_CURSORY_DETAIL, multiline:Boolean = false):String = {
    val filteredObjs = objs.map(_.getDescriptionSafe(mode, perspectiveContainer)).filter(_.isDefined).map(_.get).toList.sorted

    // No contents
    if (filteredObjs.size == 0) {
      if (multiline) return "\tnothing"
      return "nothing"
    }

    // Single line
    if (!multiline) return filteredObjs.mkString(", ")

    // Multi-line
    val os = new StringBuilder
    for (desc <- filteredObjs) {
      os.append("\t" + desc + "\n")
    }

    return os.toString
  }

}
