package scienceworld.objects.devices

import scienceworld.properties.{HeatSourcePropertiesOven, IsActivableDeviceOff, IsContainer, IsNotContainer, MoveableProperties}
import scienceworld.struct.EnvObject.MODE_DETAILED
import util.StringHelpers

class StopWatch extends Device {
  this.name = "stopwatch"

  this.propDevice = Some(new IsActivableDeviceOff())
  this.propContainer = Some( new IsNotContainer() )
  this.propMoveable = Some(new MoveableProperties(isMovable = true))

  // Stopwatch-related variables
  var stopwatchCurTime:Int = 0
  var stopwatchUserTime:Int = 0

  override def tick():Boolean = {
    // If it's activated, then set max temp.  If deactivated, set temp to off.
    if (this.propDevice.isDefined) {
      if (this.propDevice.get.isActivated) {
        this.stopwatchCurTime += 1
        this.stopwatchUserTime = this.stopwatchCurTime
      } else {
        this.stopwatchCurTime = 0
      }
    }

    super.tick()
  }

  override def getReferents():Set[String] = {
    Set("stopwatch", "watch", "timer", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int):String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + ", which is ")
    if (this.propDevice.get.isActivated) { os.append("activated") } else { os.append("deactivated") }
    os.append(". ")

    if (mode == MODE_DETAILED) {
      os.append("The time reads " + this.stopwatchUserTime + " ticks.")
    }

    os.toString
  }

}
