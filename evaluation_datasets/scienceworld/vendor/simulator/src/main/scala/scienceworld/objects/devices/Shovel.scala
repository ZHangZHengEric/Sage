package scienceworld.objects.devices

import scienceworld.processes.{Chopping, Shovelling}
import scienceworld.properties.{GlassProp, IsContainer, IsNotContainer, IsOpenUnclosableContainer, IsUsable, IsUsableNonActivable, MetalProp, MoveableProperties, SteelProp}
import scienceworld.struct.EnvObject


class Shovel extends Device {
  this.name = "shovel"

  this.propMaterial = Some(new SteelProp())
  this.propContainer = Some( new IsNotContainer() )
  this.propDevice = Some(new IsUsableNonActivable())
  this.propMoveable = Some(new MoveableProperties(isMovable = true))


  override def useWith(patientObj:EnvObject):(Boolean, String) = {
    return Shovelling.doShovel(patientObj)
  }

  override def getReferents(): Set[String] = {
    Set("shovel", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder

    os.append("a " + this.getDescriptName())

    os.toString
  }

}


class Axe extends Device {
  this.name = "axe"

  this.propMaterial = Some(new SteelProp())
  this.propContainer = Some( new IsNotContainer() )
  this.propDevice = Some(new IsUsableNonActivable())
  this.propMoveable = Some(new MoveableProperties(isMovable = true))


  override def useWith(patientObj:EnvObject):(Boolean, String) = {
    return Chopping.doChop(patientObj)
  }

  override def getReferents(): Set[String] = {
    Set("axe", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder

    os.append("an " + this.getDescriptName())

    os.toString
  }

}
