package scienceworld.objects.substance.paint

import scienceworld.properties.{BluePaintProp, BlueVioletPaintProp, BrownPaintProp, GenericPaintProp, GreenBluePaintProp, GreenPaintProp, OrangePaintProp, RedOrangePaintProp, RedPaintProp, VioletPaintProp, VioletRedPaintProp, YellowGreenPaintProp, YellowOrangePaintProp, YellowPaintProp}
import scienceworld.struct.EnvObject

class Paint extends EnvObject {
  this.name = "paint"
  propMaterial = Some(new GenericPaintProp)

  override def getReferents(): Set[String] = {
    Set("paint", this.name, this.getDescriptName())
  }

  override def getDescription(mode:Int): String = {
    return "" + this.getDescriptName()
  }
}


/*
 * Paint colours
 */

// Primary
class RedPaint extends Paint {
  this.name = "red paint"
  propMaterial = Some(new RedPaintProp())
}

class BluePaint extends Paint {
  this.name = "blue paint"
  propMaterial = Some(new BluePaintProp())
}

class YellowPaint extends Paint {
  this.name = "yellow paint"
  propMaterial = Some(new YellowPaintProp())
}

// Secondary
class VioletPaint extends Paint {
  this.name = "violet paint"
  propMaterial = Some(new VioletPaintProp())
}

class GreenPaint extends Paint {
  this.name = "green paint"
  propMaterial = Some(new GreenPaintProp())
}

class OrangePaint extends Paint {
  this.name = "orange paint"
  propMaterial = Some(new OrangePaintProp())
}

// Catch-all
class BrownPaint extends Paint {
  this.name = "brown paint"
  propMaterial = Some(new BrownPaintProp())
}

// Tertiary
class YellowOrangePaint extends Paint {
  this.name = "yellow-orange paint"
  propMaterial = Some(new YellowOrangePaintProp())
}

class RedOrangePaint extends Paint {
  this.name = "red-orange paint"
  propMaterial = Some(new RedOrangePaintProp())
}

class VioletRedPaint extends Paint {
  this.name = "violet-red paint"
  propMaterial = Some(new VioletRedPaintProp())
}

class BlueVioletPaint extends Paint {
  this.name = "blue-violet paint"
  propMaterial = Some(new BlueVioletPaintProp())
}

class GreenBluePaint extends Paint {
  this.name = "green-blue paint"
  propMaterial = Some(new GreenBluePaintProp())
}

class YellowGreenPaint extends Paint {
  this.name = "yellow-green paint"
  propMaterial = Some(new YellowGreenPaintProp())
}
