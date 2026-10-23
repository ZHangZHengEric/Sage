package scienceworld.properties

trait EdibilityProperties {
  var isEdible:Boolean            = true
  var isPoisonous:Boolean         = false

  def toJSON():String = {
    val os = new StringBuilder()
    os.append("{")
    os.append("\"isEdible\":" + this.isEdible + ",")
    os.append("\"isPoisonous\":" + this.isPoisonous)
    os.append("}")

    return os.toString()
  }

}


class Edible extends EdibilityProperties {
  isEdible                        = true
  isPoisonous                     = false
}

class Poisonous extends EdibilityProperties {
  isEdible                        = true
  isPoisonous                     = false
}

class Inedible extends EdibilityProperties {
  isEdible                        = false
  isPoisonous                     = false
}
