package scienceworld.properties

class ContainerProperties(
  var isContainer:Boolean         = true,
  var isOpen:Boolean              = false,
  var isClosable:Boolean          = false,     // Can the container be opened and closed?
  // Add properties for storing different kinds of things?  (e.g. can store solids?  liquids?  gasses? etc)
  ) {

  def toJSON():String = {
    val os = new StringBuilder()
    os.append("{")
    os.append("\"isContainer\":\"" + this.isContainer + "\",")
    os.append("\"isOpen\":" + this.isOpen + ",")
    os.append("\"isClosable\":" + this.isClosable)
    os.append("}")

    return os.toString()
  }

}


class IsContainer extends ContainerProperties {
  isContainer                     = true
  isOpen                          = false
  isClosable                      = true
}

class IsNotContainer extends ContainerProperties {
  isContainer                     = false
  isOpen                          = false
  isClosable                      = false
}

class IsOpenUnclosableContainer extends ContainerProperties {
  isContainer                     = true
  isOpen                          = true
  isClosable                      = false
}
