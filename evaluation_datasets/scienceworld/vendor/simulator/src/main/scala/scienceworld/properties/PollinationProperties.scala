package scienceworld.properties

import scienceworld.objects.livingthing.plant.Plant
import scienceworld.processes.genetics.ChromosomePair

class PollinationProperties {

  var pollinationStep:Int = 0
  var stepsUntilFruitingBodyForms:Int = 5
  var parent2ChromosomePairs:Option[ChromosomePair] = None

}
