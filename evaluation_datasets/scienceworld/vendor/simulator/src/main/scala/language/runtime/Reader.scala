package language.runtime

import java.io.File
import language.model.{ActionRequestDef, PredicateDef, Program, RuleDef}
import language.parser.Parser
import language.runtime.runners.ActionRunner

import scala.collection.mutable
import scala.io.Source

class Reader {

}

object Reader {

  def parseProgramFromFile(parser:Parser, scriptFilename:String, referringFilename:String = "", filenamesAlreadyImported:mutable.Set[String] = mutable.Set[String]()): (Program, Boolean, mutable.Set[String]) = {
    println(" * parseProgramFromFile: " + scriptFilename)
    // Path to file
    val fileAbsolute = new File(scriptFilename).getCanonicalPath()                            // With filename
    val pathAbsolute = fileAbsolute.substring(0, fileAbsolute.lastIndexOf(File.separator))    // Without filename (just the path)

    filenamesAlreadyImported.add(fileAbsolute)

    // Read file and store as string
    var scriptStr:String = ""
    try {
      scriptStr = fileToString(fileAbsolute)
    } catch {
      case _:Throwable => {
        println ("ERROR: Could not import file (" + fileAbsolute + ") referenced by (" + referringFilename + ").")
        sys.exit(1)
      }
    }

    // Parse the program
    var (program, success) = parseProgramFromString(parser, scriptStr, originalFilename = fileAbsolute)

    // Perform class inheritance (locally, within the file)
    program = program.inheritClassProperties()

    // Check for any errors in the file itself
    if (program.hasErrors()) {
      val errorStrs = program.getErrors()
      println(errorStrs.length + " error(s) were found after importing file (" + scriptFilename + "):")
      for (errorStr <- errorStrs) {
        println(errorStr)
      }
      sys.exit(1)
    }

    // Check for any files that need to be imported
    if (program.importList.isDefined) {
      for (importFile <- program.importList.get) {
        println("Importing file: " + importFile.filename)
        // Get absolute filename
        val importFilename = new File(pathAbsolute + File.separator + importFile.filename).getCanonicalPath()

        // Check to make sure another file hasn't already imported this file
        if (!filenamesAlreadyImported.contains(importFilename)) {
          // Import file
          val (programImport, successImport, parsedFilesImport) = parseProgramFromFile(parser, importFilename, referringFilename = scriptFilename, filenamesAlreadyImported = filenamesAlreadyImported)
          // Add list of any files imported by the import
          filenamesAlreadyImported ++= parsedFilesImport
          // Check for failure
          if (!successImport) return (new Program, false, filenamesAlreadyImported)
          // If success, add programs together
          program = program + programImport           // TODO: Also pass/keep track of source file names when combining programs, to allow for more informative error messages

          // Perform class inheritance
          program = program.inheritClassProperties()

          // Check if adding the programs together produced any errors
          if (program.hasErrors()) {
            val errorStrs = program.getErrors()
            println(errorStrs.length + " error(s) were found after importing file (" + importFilename + "):")
            for (errorStr <- errorStrs) {
              println(errorStr)
            }
            sys.exit(1)
          }

        } else {
          println ("Already imported: " + importFilename + " (SKIPPING)")
        }
      }
    }

    (program, success, filenamesAlreadyImported)
  }


  // Parse a program from a string
  def parseProgramFromString(parser:Parser, script:String, originalFilename:String = ""): (Program, Boolean) = {

    parser.parseAll(parser.program, script) match {
      // Success case
      case parser.Success(r, n) => r match {

        case program: Program => {
          println("Program successfully parsed.")
          return (program, true)
        }

      }

      // Error cases
      case parser.Error(msg, next) => {
        val errorStr = "line " + next.pos.line + ", column " + next.pos.column + ": " + msg + "\n" + next.pos.longString
        println("Failure Parsing: " + originalFilename + "\n" + errorStr)
        return (new Program, false)
      }
      case parser.Failure(msg, next) => {
        val errorStr = "line " + next.pos.line + ", column " + next.pos.column + ": " + msg + "\n" + next.pos.longString
        println("Failure Parsing: " + originalFilename + "\n" + errorStr)
        return (new Program, false)
      }
      case _ => {
        println ("Unknown error while parsing.")
        return (new Program, false)
      }

    }

  }


  /*
   * Supporting functions
   */
  def fileToString(filename:String) = {
    val file = Source.fromFile(filename)
    val str = file.mkString
    // Return
    str
  }


  /*
   * Main
   */
  def main(args:Array[String]): Unit = {

    // Step 1: Load script

    val exampleScriptStr =
      """println()
        |""".stripMargin

    val exampleScriptStr1 =
      """println()
        |println()
        |println()
        |def blah() = { println() }
        |def blah(a=b) = { println() }
        |def blah(a=b, c=d, e=f) = { println() }
        |def blah(a=b, c=d, e=f) = { println() }
        |""".stripMargin

    //val scriptFilename = "tests/test1.env"
    //val scriptFilename = "tests/test2.env"
    val scriptFilename = "tests/test3.env"

    // Step 2: Parse script
    val parser = new Parser()
    //val (program, success) = parseProgramFromString(parser, exampleScriptStr1)
    val (program, success, importedFiles) = parseProgramFromFile(parser, scriptFilename)



    if (!success) {
      println ("Parse unsuccessful. ")
      sys.exit(1)
    }

    println("Program:")
    println(program.toString())

    println("")

    // Step 3A: Create action space handler
    val possibleActions = program.actions.getOrElse(List.empty[ActionRequestDef]).toArray
    val actionRunner = new ActionRunner(possibleActions, program.taxonomy)

    // Step 3: Run interpreter / initialization
    println("Interpreter:")
    val interpreter = new Interpreter(program.definesLUT, program.classLUT, actionRunner)
    val result = interpreter.walkOneStep(program.statements.get)

    if (result.success == true) {
      println("Interpreter completed successfully. ")
    } else {
      println("Interpreter exited with error. ")
      sys.exit(1)
    }

    // Step 4: Run agent



    val numIter = 2
    for (curIter <- 0 until numIter) {
      println("---------------------------------------")
      println(" Iteration " + curIter)
      println("---------------------------------------")

    }

  }

}
