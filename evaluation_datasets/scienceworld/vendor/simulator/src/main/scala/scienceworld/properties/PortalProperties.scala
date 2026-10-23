package scienceworld.properties

import scienceworld.struct.EnvObject

class PortalProperties(var isOpen:Boolean,
                       var isOpenable:Boolean,
                       var connectsFrom:EnvObject,
                       var connectsTo:EnvObject,
                       val isLockable:Boolean,
                       val isLocked:Boolean) {

  def toJSON():String = {
    val os = new StringBuilder()
    os.append("{")
    os.append("\"isOpen\":" + this.isOpen + ",")
    os.append("\"isOpenable\":" + this.isOpenable + ",")
    os.append("\"connectsFrom\": \"" + this.connectsFrom.uuid + "\",")
    os.append("\"connectsTo\": \"" + this.connectsTo.uuid + "\",")
    os.append("\"isLockable\":" + this.isLockable + ",")
    os.append("\"isLocked\":" + this.isLocked)
    os.append("}")

    return os.toString()
  }

}
