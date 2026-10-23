package language.struct

import java.io.PrintWriter

import scala.collection.mutable
import scala.collection.mutable.ArrayBuffer

/*
 * A storage class for representing a tree taxonomy
 */

class Taxonomy(val rootNodeName:String = "") {
  val lut = mutable.Map[String, TreeNode]()
  val rootNodeNames = mutable.Set[String]()

  // Add a default root node
  if (rootNodeName != "") this.addRoot(this.rootNodeName)

  def contains(nodeName:String):Boolean = lut.contains(nodeName)

  def getNode(nodeName:String):Option[TreeNode] = lut.get(nodeName)

  def keySet():Set[String] = scala.collection.immutable.TreeSet.empty[String] ++ lut.keySet

  def getRootNames():Set[String] = scala.collection.immutable.TreeSet.empty[String] ++ rootNodeNames

  def addRoot(nodeName:String): Unit = {
    val newNode = new TreeNode(nodeName, None)
    lut(nodeName) = newNode
    rootNodeNames.add(nodeName)
  }

  def addLink(nodeName:String, parentName:String, autoAddParent:Boolean = false):(Boolean, String) = {       // (Success, errorString)
    // Check to make sure the node being added doesn't already exist
    //if (lut.contains(nodeName)) return (false, "ERROR: Requested node to be added (" + nodeName + ") already exists.")
    if (!lut.contains(parentName)) {
      if (!autoAddParent) {
        return (false, "ERROR: Parent node (" + parentName + ") not found in taxonomy.")
      } else {
        this.addRoot(parentName)
      }
    }

    val parentNode = lut.get(parentName).get
    var newNode = new TreeNode(nodeName, Some(parentNode))
    if (lut.contains(nodeName)) {
      // Node already exists
      newNode = this.getNode(nodeName).get
      if (newNode.parent.isEmpty) newNode.parent = Some(parentNode)
      if (newNode.parent.isDefined) {
        if (newNode.parent.get.name != parentName) return (false, "ERROR: Adding a link between (" + nodeName + " -> " + parentName + "), but (" + nodeName + ") already has an existing parent defined (" + newNode.parent.get.name + ").")
      }
    }
    parentNode.addChild(newNode)
    lut(nodeName) = newNode

    if (rootNodeNames.contains(nodeName)) {
      // nodeName is no longer a root
      rootNodeNames.remove(nodeName)
    }

    return (true, "")
  }

  // e.g. for "cat", would return "animal", "living thing", "object"
  def getHypernyms(nodeName:String):(Boolean, String, Array[String]) = {                // (Success, errorString, return value (Array[String]) )
    // Check to name sure that the node exists
    if (!lut.contains(nodeName)) return (false, "ERROR: Requested node (" + nodeName + ") not found in taxonomy.", Array.empty[String])

    val hypernyms = lut.get(nodeName).get.getHypernyms()
    // Return
    (true, "", hypernyms)
  }

  // e.g. for "cat", would return "lion", "tiger"
  def getDirectHyponyms(nodeName:String):(Boolean, String, Set[String]) = {             // (Success, errorString, return value (Set[String]) )
    val out = mutable.Set[String]()
    if (!lut.contains(nodeName)) return (false, "ERROR: Requested node (" + nodeName + ") not found in taxonomy.", Set.empty[String])

    for (name <- lut.keys) {
      val node = lut.get(name).get
      if ((node.parent.isDefined) && (node.parent.get.name == nodeName)) {
        out.add(node.name)
      }
    }

    // Return
    (true, "", scala.collection.immutable.TreeSet.empty[String] ++ out)
  }


  def isKindOf(queryNodeName:String, parentNodeName:String):(Boolean, String, Boolean) = {      // (Success, errorString, return value (isKindOf) )
    // Check to make sure the node being added doesn't already exist
    if (!lut.contains(queryNodeName)) return (false, "ERROR: Query node (" + queryNodeName + ") not found in taxonomy.", false)
    if (!lut.contains(parentNodeName)) return (false, "ERROR: Parent node (" + parentNodeName + ") not found in taxonomy.", false)

    val queryNode = lut.get(queryNodeName).get
    if (queryNode.isKindOf(parentNodeName)) return (true, "", true)
    // Default return
    (true, "", false)
  }


  /*
   * Operators
   */
  def combine(that:Taxonomy):(Boolean, Array[String]) = {           // (Success, errorStrings)
    val errorStrs = new ArrayBuffer[String]()

    for (rootName <- that.getRootNames()) {
      // If a new root doesn't exist in the current tree, add it
      if (!this.contains(rootName)) this.addRoot(rootName)

      // Then, recursively add the nodes
      val (successBranch, errorsBranch) = this.addBranch(rootName, that)
      if (errorsBranch.length > 0) errorStrs.insertAll(errorStrs.length, errorsBranch)
    }

    // If errors, return failure
    if (errorStrs.length > 0) return (false, errorStrs.toArray)
    // Otherwise, return success
    return (true, errorStrs.toArray)
  }

  // Add a branch from 'that' tree to 'this' tree, recursively
  private def addBranch(nodeName:String, that:Taxonomy):(Boolean, Array[String]) = {           // (Success, errorStrings)
    val errorStrs = new ArrayBuffer[String]()

    val children = that.getNode(nodeName).get.children
    for (child <- children.toArray.sortBy(_.name)) {
      val (successLink, errorsLink) = this.addLink(child.name, nodeName)        // Add link
      if (errorsLink.length > 0) errorStrs.append(errorsLink)
      val (successBranch, errorsBranch) = this.addBranch(child.name, that)      // Recurse
      if (errorsBranch.length > 0) errorStrs.insertAll(errorStrs.length, errorsBranch)
    }

    // If errors, return failure
    if (errorStrs.length > 0) return (false, errorStrs.toArray)
    // Otherwise, return success
    return (true, errorStrs.toArray)
  }

  /*
   * Saving
   */
  // Serializes to string, then saves.  Loaded by Taxonomy.loadFromFile() in static object
  def saveToFile(filenameOut:String) = {
    val pw = new PrintWriter(filenameOut)
    pw.print( this.toString() )
    pw.close()
  }


  /*
   * String methods
   */
  override def toString():String = {
    val os = new mutable.StringBuilder()

    for (rootName <- this.getRootNames()) {
      val rootNode = lut.get(rootName).get
      os.append( rootNode.toTreeString(indentLevel = 0) )
    }

    os.toString()
  }

}


class TreeNode(val name:String, var parent:Option[TreeNode], val children:mutable.Set[TreeNode] = mutable.Set[TreeNode]()) {

  def addChild(node:TreeNode) = children.add(node)

  // Get the hypernyms of this treenode (e.g. cat :  cat -> mammal -> animal -> living thing)
  def getHypernyms():Array[String] = {
    if (parent.isDefined) return Array(name) ++ parent.get.getHypernyms()
    return Array(name)
  }

  // Check to see if this treenode is a kind_of another tree node (i.e. if 'kindof' is one of its hypernyms)
  def isKindOf(kindof:String):Boolean = {
    if (name == kindof) return true
    if (parent.isEmpty) return false
    return parent.get.isKindOf(kindof)
  }


  /*
   * String methods
   */
  def toTreeString(indentLevel:Int = 0):String = {
    val os = new mutable.StringBuilder()
    os.append(("\t" * indentLevel) + this.name + "\n")
    for (child <- this.children.toArray.sortBy(_.name)) {
      os.append( child.toTreeString(indentLevel+1) )
    }
    return os.toString()
  }

}


object Taxonomy {

  def loadFromFile(filename:String):Option[Taxonomy] = {
    println ("* Taxonomy.loadFromFile(): Loading Taxonomy from file... " + filename)
    var out:Option[Taxonomy] = None

    var lastIndentLevel = 1
    var lineCount:Int = 0
    var nameStack = new ArrayBuffer[String]()

    for (line <- io.Source.fromFile(filename, "UTF-8").getLines()) {
      if (line.length > 0) {
        // Step 1: Parse line
        val fields = line.split("\t")
        val name = fields.last
        val indentLevel = fields.length

        println ("line: " + line + "      lastIndentLevel: " + lastIndentLevel + "   indentLevel: " + indentLevel)
        println ("    nameStack: " + nameStack.mkString(", "))
        // Step 2: Store line
        if (lineCount == 0) {
          // First line -- this should be the root of the taxonomy
          out = Some(new Taxonomy(name))
          nameStack.append(name)
        } else {
          // Subsequent lines
          if (indentLevel <= nameStack.size) {
            nameStack = nameStack.slice(0, indentLevel-1)
          } else {
            // Do not remove, but check that the jump is only 1
            if (indentLevel > lastIndentLevel + 1) throw new RuntimeException("ERROR: Taxonomy has more than one indentation between subsequent lines around line " + lineCount + " (" + filename + ").")
          }
          println ("    nameStack: " + nameStack.mkString(", "))
          if (indentLevel == 1) {
            // Root node
            out.get.addRoot(name)
          } else {
            // Non-root node
            val parent = nameStack.last
            out.get.addLink(name, parent)
            nameStack.append(name)
          }
        }

        lastIndentLevel = indentLevel
      }
      lineCount += 1
    }

    println ("* Taxonomy.loadFromFile(): Read " + lineCount + " lines...")

    // Return
    out
  }

  def main(args:Array[String]): Unit = {
    val taxonomy = new Taxonomy

    taxonomy.addLink("Organism", taxonomy.rootNodeName)
    taxonomy.addLink("Mammal", "Organism")
    taxonomy.addLink("Cat", "Mammal")
    taxonomy.addLink("Dog", "Mammal")
    taxonomy.addLink("Bear", "Mammal")
    taxonomy.addLink("Reptile", "Organism")
    taxonomy.addLink("Lizard", "Reptile")
    taxonomy.addLink("Gecko", "Reptile")
    taxonomy.addLink("Bird", "Organism")

    val taxonomy2 = new Taxonomy("")
    taxonomy2.addRoot("Bird")
    taxonomy2.addRoot("Organism")
    taxonomy2.addLink("Bluejay", "Bird")
    taxonomy2.addLink("Robin", "Bird")
    taxonomy2.addLink("Owl", "Bird")
    taxonomy2.addLink("Fish", "Organism")
    taxonomy2.addLink("Goldfish", "Fish")

    val taxonomy3 = new Taxonomy("")
    taxonomy3.addRoot("Any")
    taxonomy3.addLink("Object", "Any")
    taxonomy3.addLink("Fish", "Object")


    println ("Taxonomy1:")
    println(taxonomy)

    println (taxonomy.getHypernyms("Gecko")._3.mkString(", "))

    println (taxonomy.isKindOf("Gecko", "Organism") )
    println (taxonomy.isKindOf("Dog", "Reptile") )

    println ("Taxonomy2:")
    println(taxonomy2.keySet().mkString(", "))
    println(taxonomy2)

    println ("Taxonomy3:")
    println(taxonomy3.keySet().mkString(", "))
    println(taxonomy3)


    taxonomy.saveToFile("savetest.txt")
/*
    val loaded = Taxonomy.loadFromFile("savetest.txt")
    println(loaded.get.toString())

 */

    // Combine
    val (success1, errorStrs1) = taxonomy.combine(taxonomy2)
    val (success2, errorStrs2) = taxonomy.combine(taxonomy3)

    println ("Combined:")
    println(taxonomy)

    if ((errorStrs1.length > 0) || (errorStrs2.length > 0)) {
      println ("ERRORS: \n" + errorStrs1.mkString("\n") + errorStrs2.mkString("\n"))
    }


    val loaded1 = Taxonomy.loadFromFile("tests/test2.tax").get
    println(loaded1)
  }


}
