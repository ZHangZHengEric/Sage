package scienceworld.properties


trait DeviceProperties {
  var isActivable:Boolean               = false
  var isActivated:Boolean               = false
  var isUsable:Boolean                  = false
  var isBroken:Boolean                  = false       // For devices that are broken (e.g. for environment ablations)

  def toJSON():String = {
    val os = new StringBuilder()
    os.append("{")
    os.append("\"isActivable\":" + this.isActivable + ",")
    os.append("\"isActivated\":" + this.isActivated + ",")
    os.append("\"isUsable\":" + this.isUsable + ",")
    os.append("\"isBroken\":" + this.isBroken)
    os.append("}")

    return os.toString()
  }

}


class IsActivableDeviceOff extends DeviceProperties {
  isActivable                           = true
  isActivated                           = false
}

class IsActivableDeviceOn extends DeviceProperties {
  isActivable                           = true
  isActivated                           = true
}

class IsNotActivableDeviceOff extends DeviceProperties {
  isActivable                           = false
  isActivated                           = false
}

class IsNotActivableDeviceOn extends DeviceProperties {
  isActivable                           = false
  isActivated                           = true
}


// For instantaneous use devices (like a thermometer)
class IsUsable extends DeviceProperties {
  isUsable                              = true
}

// For instantaneous use devices (like a shovel)
class IsUsableNonActivable extends DeviceProperties {
  isActivable                           = false
  isActivated                           = false
  isUsable                              = true
}
