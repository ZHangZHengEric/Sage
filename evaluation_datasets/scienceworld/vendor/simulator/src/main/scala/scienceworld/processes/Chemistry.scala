package scienceworld.processes

import scienceworld.objects.document.ColoredPaper
import scienceworld.objects.substance.food.{Dough, FruitSalad, MixedNuts, Sandwich, Smores}
import scienceworld.objects.substance.paint.{BlueVioletPaint, BrownPaint, GreenBluePaint, GreenPaint, OrangePaint, RedOrangePaint, VioletPaint, VioletRedPaint, YellowGreenPaint, YellowOrangePaint}
import scienceworld.objects.substance.{Rust, SaltWater, SoapyWater, SodiumAcetate, SugarWater}
import scienceworld.properties.RedOrangePaintProp
import scienceworld.struct.EnvObject

class Chemistry {

}

object Chemistry {

  /*
   * Helper functions
   */
  // Try to find a substance in a container
  private def getSubstance(container:EnvObject, substanceName:String, stateOfMatter:String = ""):Option[EnvObject] = {
    for (cObj <- container.getContainedObjects()) {
      if (cObj.name == substanceName) {
        if (stateOfMatter.length == 0) return Some(cObj)
        if ((cObj.propMaterial.isDefined) && (cObj.propMaterial.get.stateOfMatter == stateOfMatter)) return Some(cObj)
      }
      if ((cObj.propMaterial.isDefined) && (cObj.propMaterial.get.substanceName == substanceName)) {
        if (cObj.propMaterial.get.stateOfMatter == stateOfMatter) return Some(cObj)
      }
    }
    // If we reach here, no matches were found
    return None
  }

  // Check for any N (e.g. any 2) objects to be defined in a list of objects.  e.g. check for any 2 paints to be defined.
  // Used as a catch-all (e.g. if a lot of paints are together, then they'll mix to form brown).
  // If 'deleteIfFound' is true, then it will delete those found (e.g. delete the N paints).  'expelContents' will expel contents of deleted objects, if deleted.
  private def checkForAnyN(in:Array[Option[EnvObject]], numToFind:Int = 2, deleteIfFound:Boolean = false, expelContents:Boolean = false):Boolean = {
    // Step 1: Count number defined
    var numFound:Int = 0
    for (elem <- in) {
      if (elem.isDefined) numFound += 1
    }

    // Step 2: If we didn't find the correct number, then exit
    if (numFound != numToFind) return false

    // Step 3: If delete is requested, then delete those found
    if (deleteIfFound) {
      for (elem <- in) {
        if (elem.isDefined) elem.get.delete(expelContents = expelContents)
      }
    }

    // Return
    true
  }

  /*
   * Mixing
   */

  // Mix the contents of a container
  def mixContainer(container:EnvObject):(Boolean, String) = {
    val contents = container.getContainedObjectsNotHidden()

    print("MIX: Contents: " + contents.toArray.sortBy(_.uuid).map(_.toString()).mkString("\n"))

    // Case: Zero substances
    if (contents.size == 0) {
      return (false, "That container is empty, so there are no items to mix.")
    }

    // Case: One substance
    if (contents.size == 1) {
      val item = contents.toArray.last
      return (false, "There is only one thing (" + item.getDescriptName() + ")")
    }

    val water = this.getSubstance(container, "water", "liquid")
    val sodium = this.getSubstance(container, "sodium", "solid")
    val sodiumChloride = this.getSubstance(container, substanceName = "sodium chloride", "solid")
    val soap = this.getSubstance(container, "soap")
    val flour = this.getSubstance(container, "flour")
    val sugar = this.getSubstance(container, "sugar")
    val chocolate = this.getSubstance(container, "chocolate")
    val marshmallow = this.getSubstance(container, "marshmallow")

    val ironblock = this.getSubstance(container, "iron block")

    val sodiumbicarbonate = this.getSubstance(container, "sodium bicarbonate")
    val aceticacid = this.getSubstance(container, "acetic acid")

    val peanut = this.getSubstance(container, "peanut")
    val almond = this.getSubstance(container, "almond")
    val cashew = this.getSubstance(container, "cashew")

    val apple = this.getSubstance(container, "apple")
    val orange = this.getSubstance(container, "orange")
    val banana = this.getSubstance(container, "banana")

    val jam = this.getSubstance(container, "jam")
    val bread = this.getSubstance(container, "bread")

    val paper = this.getSubstance(container, "paper")


    // Paints
    // Primary
    val paintRed        = this.getSubstance(container, substanceName = "red paint", stateOfMatter = "liquid")
    val paintBlue       = this.getSubstance(container, substanceName = "blue paint", stateOfMatter = "liquid")
    val paintYellow     = this.getSubstance(container, substanceName = "yellow paint", stateOfMatter = "liquid")
    // Secondary
    val paintViolet     = this.getSubstance(container, substanceName = "violet paint", stateOfMatter = "liquid")
    val paintGreen      = this.getSubstance(container, substanceName = "green paint", stateOfMatter = "liquid")
    val paintOrange     = this.getSubstance(container, substanceName = "orange paint", stateOfMatter = "liquid")
    // Tertiary
    val paintYellowOrange = this.getSubstance(container, substanceName = "yellow-orange paint", stateOfMatter = "liquid")
    val paintRedOrange    = this.getSubstance(container, substanceName = "red-orange paint", stateOfMatter = "liquid")
    val paintVioletRed    = this.getSubstance(container, substanceName = "violet-red paint", stateOfMatter = "liquid")
    val paintBlueViolet   = this.getSubstance(container, substanceName = "blue-violet paint", stateOfMatter = "liquid")
    val paintGreenBlue    = this.getSubstance(container, substanceName = "green-blue paint", stateOfMatter = "liquid")
    val paintGreenYellow  = this.getSubstance(container, substanceName = "green-yellow paint", stateOfMatter = "liquid")
    // Catch-all
    val paintBrown        = this.getSubstance(container, substanceName = "brown paint", stateOfMatter = "liquid")

    // All paints (for catch-all)
    val paintsAll         = Array(paintRed, paintBlue, paintYellow, paintViolet, paintGreen, paintOrange, paintYellowOrange, paintRedOrange, paintVioletRed, paintBlueViolet, paintGreenBlue, paintGreenYellow, paintBrown)

    /*
     * Case: 2 SUBSTANCES
     */
    if (contents.size == 2) {

      // Salt Water
      if ((water.isDefined) && (sodiumChloride.isDefined)) {
        water.get.delete()
        sodiumChloride.get.delete()

        val saltWater = new SaltWater()
        container.addObject(saltWater)

        return (true, "Sodium chloride and water mix to produce salt water.")
      }

      // Soapy water
      if ((water.isDefined) && (soap.isDefined)) {
        water.get.delete()
        soap.get.delete()

        val soapyWater = new SoapyWater()
        container.addObject(soapyWater)

        return (true, "Soap and water mix to produce soapy water.")
      }

      // Sugar water
      if ((water.isDefined) && (sugar.isDefined)) {
        water.get.delete()
        sugar.get.delete()

        val sugarWater = new SugarWater()
        container.addObject(sugarWater)

        return (true, "Sugar and water mix to produce sugar water.")
      }

      // Dough
      if ((water.isDefined) && (flour.isDefined)) {
        water.get.delete()
        flour.get.delete()

        val dough = new Dough()
        container.addObject(dough)

        return (true, "Flour and water mix to produce dough.")
      }

      // Smores
      if ((chocolate.isDefined) && (marshmallow.isDefined)) {
        chocolate.get.delete()
        marshmallow.get.delete()

        container.addObject(new Smores())

        return (true, "Chocolate and marshmallow mix to produce smores.")
      }

      // Rust
      if ((water.isDefined) && (ironblock.isDefined)) {
        water.get.delete()
        ironblock.get.delete()

        val rust = new Rust()
        container.addObject(rust)

        return (true, "Iron block and water mix to produce rust.")
      }

      // Sodium acetate
      if ((sodiumbicarbonate.isDefined) && (aceticacid.isDefined)) {
        sodiumbicarbonate.get.delete()
        aceticacid.get.delete()

        container.addObject( new SodiumAcetate() )

        return (true, "Sodium bicarbonate and acetic acid mix to produce sodium acetate.")
      }


      // 2-ingredient sandwiches
      if (bread.isDefined && peanut.isDefined) {
        bread.get.delete()
        peanut.get.delete()
        container.addObject(new Sandwich("peanut butter"))
        return (true, "Bread and peanuts mix to produce a peanut butter sandwich.")
      }

      if (bread.isDefined && jam.isDefined) {
        bread.get.delete()
        jam.get.delete()
        container.addObject(new Sandwich("jam"))
        return (true, "Bread and peanuts mix to produce a jam sandwich.")
      }

      if (bread.isDefined && banana.isDefined) {
        bread.get.delete()
        banana.get.delete()
        container.addObject(new Sandwich("banana"))
        return (true, "Bread and peanuts mix to produce a banana sandwich.")
      }



      // Dying paper

      if ((paper.isDefined) && (paintRed.isDefined)) {
        paper.get.delete()
        paintRed.get.delete()
        container.addObject( new ColoredPaper("red") )
        return (true, "Paper and blue paint mix to produce red paper.")
      }

      if ((paper.isDefined) && (paintGreen.isDefined)) {
        paper.get.delete()
        paintGreen.get.delete()

        container.addObject( new ColoredPaper("green") )

        return (true, "Paper and blue paint mix to produce green paper.")
      }

      if ((paper.isDefined) && (paintBlue.isDefined)) {
        paper.get.delete()
        paintBlue.get.delete()

        container.addObject( new ColoredPaper("blue") )

        return (true, "Paper and blue paint mix to produce blue paper.")
      }

      if ((paper.isDefined) && (paintOrange.isDefined)) {
        paper.get.delete()
        paintOrange.get.delete()

        container.addObject( new ColoredPaper("orange") )

        return (true, "Paper and blue paint mix to produce orange paper.")
      }

      if ((paper.isDefined) && (paintYellow.isDefined)) {
        paper.get.delete()
        paintYellow.get.delete()

        container.addObject( new ColoredPaper("yellow") )

        return (true, "Paper and blue paint mix to produce yellow paper.")
      }

      if ((paper.isDefined) && (paintViolet.isDefined)) {
        paper.get.delete()
        paintViolet.get.delete()

        container.addObject( new ColoredPaper("violet") )

        return (true, "Paper and blue paint mix to produce violet paper.")
      }


      /*
       * Paints
       */
      // Secondary colours
      if ((paintRed.isDefined) && (paintBlue.isDefined)) {
        paintRed.get.delete()
        paintBlue.get.delete()
        container.addObject( new VioletPaint() )
        return (true, "Red and blue paint mix to produce violet paint.")
      }

      if ((paintBlue.isDefined) && (paintYellow.isDefined)) {
        paintBlue.get.delete()
        paintYellow.get.delete()
        container.addObject( new GreenPaint() )
        return (true, "Blue and yellow paint mix to produce green paint.")
      }

      if ((paintYellow.isDefined) && (paintRed.isDefined)) {
        paintYellow.get.delete()
        paintRed.get.delete()
        container.addObject( new OrangePaint() )
        return (true, "Yellow and red paint mix to produce orange paint.")
      }

      // Tertiary colours
      if ((paintYellow.isDefined) && (paintOrange.isDefined)) {
        paintYellow.get.delete()
        paintOrange.get.delete()
        container.addObject( new YellowOrangePaint() )
        return (true, "Yellow and orange paint mix to produce yellow-orange paint.")
      }

      if ((paintOrange.isDefined) && (paintRed.isDefined)) {
        paintOrange.get.delete()
        paintRed.get.delete()
        container.addObject( new RedOrangePaint() )
        return (true, "Red and orange paint mix to produce red-orange paint.")
      }

      if ((paintRed.isDefined) && (paintViolet.isDefined)) {
        paintRed.get.delete()
        paintViolet.get.delete()
        container.addObject( new VioletRedPaint() )
        return (true, "Violet and red paint mix to produce violet-red paint.")
      }

      if ((paintViolet.isDefined) && (paintBlue.isDefined)) {
        paintViolet.get.delete()
        paintBlue.get.delete()
        container.addObject( new BlueVioletPaint() )
        return (true, "Blue and violet paint mix to produce blue-violet paint.")
      }

      if ((paintBlue.isDefined) && (paintGreen.isDefined)) {
        paintBlue.get.delete()
        paintGreen.get.delete()
        container.addObject( new GreenBluePaint() )
        return (true, "Blue and green paint mix to produce blue green paint.")
      }

      if ((paintGreen.isDefined) && (paintYellow.isDefined)) {
        paintGreen.get.delete()
        paintYellow.get.delete()
        container.addObject( new YellowGreenPaint() )
        return (true, "Green and yellow paint mix to produce yellow-green paint.")
      }

      // Catch-all (any 2 paints, not already covered by a rule above)
      if (this.checkForAnyN(paintsAll, numToFind = 2, deleteIfFound = true, expelContents = false)) {
        // Create brown
        container.addObject( new BrownPaint() )
        return (true, "The paints mix to produce brown paint.")
      }


    } else if (contents.size == 3) {
      /*
       * Case: 3 SUBSTANCES
       */

      // Mixed nuts
      if (peanut.isDefined && almond.isDefined && cashew.isDefined) {
        peanut.get.delete()
        almond.get.delete()
        cashew.get.delete()

        container.addObject(new MixedNuts())
        return (true, "Peanuts, almonds, and cashews mix to produce mixed nuts.")
      }

      // Fruit salad
      if (apple.isDefined && orange.isDefined && banana.isDefined) {
        apple.get.delete()
        orange.get.delete()
        banana.get.delete()

        container.addObject(new FruitSalad())
        return (true, "Apples, oranges, and bananas mix to produce fruit salad.")
      }

      // 3-ingredient sandwiches
      if (bread.isDefined && peanut.isDefined && jam.isDefined) {
        bread.get.delete()
        peanut.get.delete()
        jam.get.delete()
        container.addObject(new Sandwich("peanut butter with jam"))
        return (true, "Bread and peanuts and jam mix to produce a peanut butter with jam sandwich.")
      }

      if (bread.isDefined && peanut.isDefined && banana.isDefined) {
        bread.get.delete()
        peanut.get.delete()
        banana.get.delete()
        container.addObject(new Sandwich("peanut butter with banana"))
        return (true, "Bread and peanuts and jam mix to produce a peanut butter with banana sandwich.")
      }


      /*
       * Paints catch-all
       */
      // Catch-all (any 2 paints, not already covered by a rule above)
      if (this.checkForAnyN(paintsAll, numToFind = 3, deleteIfFound = true, expelContents = false)) {
        // Create brown
        container.addObject( new BrownPaint() )
        return (true, "The paints mix to produce brown paint.")
      }


    } else if (contents.size == 4) {
      /*
       * Case: 4 SUBSTANCES
       */

      // TODO: Add 3-substance mix combinations

      /*
       * Paints catch-all
       */
      // Catch-all (any 2 paints, not already covered by a rule above)
      if (this.checkForAnyN(paintsAll, numToFind = 4, deleteIfFound = true, expelContents = false)) {
        // Create brown
        container.addObject( new BrownPaint() )
        return (true, "The paints mix to produce brown paint.")
      }

    }


    return (false, "Mixing the contents of the " + container.getDescriptName() + " does not appear to produce anything new.")
  }

}
