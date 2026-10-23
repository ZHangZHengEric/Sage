package scienceworld.objects.document

import scienceworld.properties.{GlassProp, IsActivableDeviceOff, IsNotContainer, IsUsable, MoveableProperties, PaperProp}
import scienceworld.struct.EnvObject

import scala.util.Random

class Document extends EnvObject {
  this.name = "document"
  var title = ""
  var contents = ""

  this.propMaterial = Some(new PaperProp())
  this.propContainer = Some( new IsNotContainer() )
  this.propDevice = None
  this.propMoveable = Some(new MoveableProperties(isMovable = true))

  def readDocument():String = {
    this.title + "\n" + this.contents
  }

  override def getReferents(): Set[String] = {
    Set(this.name, this.title, this.name + " called " + this.title, this.getDescriptName(), this.getDescriptName() + " called " + this.title)
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder

    os.append("A " + this.getDescriptName() + " titled " + this.title)

    os.toString
  }

}


class Paper extends Document {
  this.name = "paper"

  override def readDocument():String = {
    val os = new StringBuilder()

    if (this.contents.length == 0) return "The paper does not have any text on it."
    os.append("The paper reads:\n")
    os.append(this.title + "\n")
    os.append(this.contents)

    os.toString()
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder

    if (this.title.length > 0) {
      os.append("A " + this.getDescriptName() + " titled " + this.title)
    } else {
      os.append("A blank " + this.getDescriptName())
    }

    os.toString
  }

}

class ColoredPaper(colorName:String) extends Document {
  this.name = colorName + " paper"

  override def readDocument():String = {
    val os = new StringBuilder()

    os.append("The paper does not have any text on it.")

    os.toString()
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder

    os.append("A " + this.getDescriptName())

    os.toString
  }

}

class Recipe extends Document {
  this.name = "recipe"

  override def readDocument():String = {
    val os = new StringBuilder()

    os.append("The recipe reads:\n")
    os.append(this.contents)

    os.toString()
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder

    os.append("A " + this.getDescriptName() + " titled " + this.title)

    os.toString
  }

}

object Recipe {
  def mkRecipe(productName:String, thingsToMix:Array[String]):Recipe = {
    val recipe = new Recipe()
    recipe.title = "instructions to make " + productName
    recipe.contents = "To make " + productName + ", you need to mix " + thingsToMix.mkString(", ") + "."
    return recipe
  }
}


class Book extends Document {
  this.title = "title"
  var author = "author"
  this.contents = "contents"

  this.name = title + " by " + author

  override def readDocument():String = {
    val os = new StringBuilder()

    os.append("The book reads:\n")
    os.append(this.title + " by " + this.author + "\n")
    os.append(this.contents)

    os.toString()
  }

  override def getReferents(): Set[String] = {
    Set("book", this.title, "book by " + this.author, this.title + " book", this.name, this.getDescriptName(), this.getDescriptName() + " by " + this.author, this.getDescriptName() + " called " + this.title)
  }

  override def getDescription(mode:Int): String = {
    val os = new StringBuilder

    os.append("A " + this.getDescriptName() + " titled " + this.title + " by " + this.author)

    os.toString

  }

}

object Book {

  def mkRandom(): EnvObject = {
    while(true) {
      val randIdx = Random.nextInt(10)    // This value should be as large or larger than the number of book options

      if (randIdx == 0) return new BookMobyDick
      if (randIdx == 1) return new BookFrankenstein
      if (randIdx == 2) return new BookSherlockHolmes
      if (randIdx == 3) return new BookPrideAndPrejudice
      if (randIdx == 4) return new BookBeowulf
      if (randIdx == 5) return new BookOriginOfSpecies
    }

    return new BookMobyDick
  }


}


class BookMobyDick extends Book {
  this.title = "Moby Dick"
  this.author = "Herman Melville"
  this.contents = "Call me Ishmael. Some years ago—never mind how long precisely—having little or no money in my purse, and nothing particular to interest me on shore, I thought I would sail about a little and see the watery part of the world. It is a way I have of driving off the spleen and regulating the circulation. Whenever I find myself growing grim about the mouth; whenever it is a damp, drizzly November in my soul; whenever I find myself involuntarily pausing before coffin warehouses, and bringing up the rear of every funeral I meet; and especially whenever my hypos get such an upper hand of me, that it requires a strong moral principle to prevent me from deliberately stepping into the street, and methodically knocking people’s hats off—then, I account it high time to get to sea as soon as I can. Call me Ishmael. Some years ago—never mind how long precisely—having little or no money in my purse, and nothing particular to interest me on shore, I thought I would sail about a little and see the watery part of the world. It is a way I have of driving off the spleen and regulating the circulation. Whenever I find myself growing grim about the mouth; whenever it is a damp, drizzly November in my soul; whenever I find myself involuntarily pausing before coffin warehouses, and bringing up the rear of every funeral I meet; and especially whenever my hypos get such an upper hand of me, that it requires a strong moral principle to prevent me from deliberately stepping into the street, and methodically knocking people’s hats off—then, I account it high time to get to sea as soon as I can. "

  this.name = "book (" + this.title + ")"
}

class BookFrankenstein extends Book {
  this.title = "Frankenstein"
  this.author = "Mary Wollstonecraft Shelley"
  this.contents = "You will rejoice to hear that no disaster has accompanied the commencement of an enterprise which you have regarded with such evil forebodings. I arrived here yesterday, and my first task is to assure my dear sister of my welfare and increasing confidence in the success of my undertaking.\n\nI am already far north of London, and as I walk in the streets of Petersburgh, I feel a cold northern breeze play upon my cheeks, which braces my nerves and fills me with delight. Do you understand this feeling? This breeze, which has travelled from the regions towards which I am advancing, gives me a foretaste of those icy climes. "

  this.name = "book (" + this.title + ")"
}

class BookSherlockHolmes extends Book {
  this.title = "Sherlock Holmes"
  this.author = "Arthur Conan Doyle"
  this.contents = "To Sherlock Holmes she is always the woman. I have seldom heard him mention her under any other name. In his eyes she eclipses and predominates the whole of her sex. It was not that he felt any emotion akin to love for Irene Adler. All emotions, and that one particularly, were abhorrent to his cold, precise but admirably balanced mind. He was, I take it, the most perfect reasoning and observing machine that the world has seen, but as a lover he would have placed himself in a false position. "

  this.name = "book (" + this.title + ")"
}

class BookPrideAndPrejudice extends Book {
  this.title = "Pride and Prejudice"
  this.author = "Jane Austen"
  this.contents = """It is a truth universally acknowledged, that a single man in possession of a good fortune, must be in want of a wife.\n\nHowever little known the feelings or views of such a man may be on his first entering a neighbourhood, this truth is so well fixed in the minds of the surrounding families, that he is considered as the rightful property of some one or other of their daughters.\n\n“My dear Mr. Bennet,” said his lady to him one day, “have you heard that Netherfield Park is let at last?” """

  this.name = "book (" + this.title + ")"
}

class BookBeowulf extends Book {
  this.title = "Beowulf"
  this.author = "Beowulf poet"
  this.contents = """Lo! the Spear-Danes’ glory through splendid achievements
                    |The folk-kings’ former fame we have heard of,
                    |How princes displayed then their prowess-in-battle.
                    |Oft Scyld the Scefing from scathers in numbers
                    |From many a people their mead-benches tore. """.stripMargin

  this.name = "book (" + this.title + ")"
}


class BookOriginOfSpecies extends Book {
  this.title = "The Foundations of the Origin of Species"
  this.author = "Charles Darwin"
  this.contents = """I. On Variation under Domestication, and on the Principles of Selection.
                    |An individual organism placed under new conditions sometimes varies in a small degree and in very trifling respects such as stature, fatness, sometimes colour, health, habits in animals and probably disposition. Also habits of life develop certain parts. Disuse atrophies.
                    |When the individual is multiplied for long periods by buds the variation is yet small, though greater and occasionally a single bud or individual departs widely from its type and continues steadily to propagate, by buds, such new kind. """.stripMargin

  this.name = "book (" + this.title + ")"
}
