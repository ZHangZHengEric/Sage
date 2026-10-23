package scienceworld.objects.taskitems

import scienceworld.objects.containers.Container
import scienceworld.objects.substance.Water
import scienceworld.properties.{CeramicProp, IsOpenUnclosableContainer}
import scienceworld.struct.EnvObject.MODE_CURSORY_DETAIL
import util.StringHelpers

/*
 *  A box intended for being an "answer box", that the agent moves specific items into to answer/complete a task.
 *  (e.g. move an electrical conductor into the blue box)
 */
class AnswerBox(colourName:String) extends Container {
  this.name = colourName + " box"
  this.propContainer = Some(new IsOpenUnclosableContainer())
  this.propMaterial = Some(new CeramicProp())

  override def tick(): Boolean = {
    super.tick()
  }

  override def getReferents(): Set[String] = {
    Set(this.name, this.getDescriptName())
  }

}
