package language.model

class ImportFile(val filename:String) extends Statement {

  override def toString():String = {
    val os = new StringBuilder

    os.append("ImportFile(")
    os.append("Filename: " + filename)
    os.append(")")

    // Return
    os.toString()
  }

}


class ImportTaxonomy(val filename:String) extends Statement {

  override def toString():String = {
    val os = new StringBuilder

    os.append("ImportTaxonomy(")
    os.append("Filename: " + filename)
    os.append(")")

    // Return
    os.toString()
  }

}
