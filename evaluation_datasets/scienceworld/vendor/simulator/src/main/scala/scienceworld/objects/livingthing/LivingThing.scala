package scienceworld.objects.livingthing

import scienceworld.processes.lifestage.LifeCycle
import scienceworld.struct.EnvObject
import scienceworld.struct.EnvObject._

class LivingThing extends EnvObject {
  this.name = "living thing"

  // Life cycle
  var lifecycle: Option[LifeCycle] = None

  override def tick(): Boolean = {
    super.tick()
  }

  override def getReferents(): Set[String] = {
    Set("living thing", "organism", this.name, this.getDescriptName())
  }

  // Make LIFE-FORM-SPECIFIC (not flower or seed-specific) text to add to the description, based off genetic traits
  def mkGeneticTraitsStr(): String = {
    return ""
  }

  override def getDescription(mode: Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName() + ". ")
    if (mode == MODE_DETAILED) {
      // Extended detail
    }

    os.toString
  }

}
